"""Endpoints for run records and comparison validity."""

import enum
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette import status

from agentic_base.db import get_session
from agentic_base.domain.outcomes import DataClass
from agentic_base.domain.run_record import (
    Approval,
    LabelUpdate,
    RunRecord,
    RunRecordCreate,
    to_payload,
    to_record,
)
from agentic_base.domain.validity import ChannelSpread, check_comparison
from agentic_base.provenance import to_openlineage, to_process_run_crate, to_prov
from agentic_base.redaction.configured import get_redactor
from agentic_base.redaction.redact import RedactionUnavailable, Redactor, redact_run

router = APIRouter(prefix="/runs", tags=["runs"])


class ChannelSpreadResponse(BaseModel):
    """One exclusion channel that fell unevenly across arms."""

    channel: str
    rate_by_arm: dict[str, float]
    lowest_arm: str
    highest_arm: str
    ratio: float
    absolute_difference: float
    description: str

    @classmethod
    def of(cls, spread: ChannelSpread) -> "ChannelSpreadResponse":
        return cls(
            channel=spread.channel,
            rate_by_arm=spread.rate_by_arm,
            lowest_arm=spread.lowest_arm,
            highest_arm=spread.highest_arm,
            ratio=spread.ratio,
            absolute_difference=spread.absolute_difference,
            description=spread.describe(),
        )


class ValidityResponse(BaseModel):
    """The verdict, with the two fields a reader must not have to infer.

    `sound` and `could_have_flagged` are derived on the domain object and are stated
    explicitly here, because a verdict that is absent from a response reads as a pass.
    """

    sound: bool
    could_have_flagged: bool
    summary: str
    arms_examined: int
    channels_examined: int
    observations_examined: int
    paired_items: int
    total_items: int
    flagged: list[ChannelSpreadResponse]


@dataclass(frozen=True)
class _Observation:
    """Adapter from a stored record to the shape the validity check needs."""

    item: str
    arm: str
    channel: str


def _redacted(payload: RunRecordCreate, redactor: Redactor) -> RunRecordCreate:
    """Redact, or refuse the write. A run classified public may be written with patterns alone
    when no detector for names can run, and its record says so; every other run is refused
    with 503, so nothing personal is stored under a redaction that did not happen."""
    try:
        return redact_run(payload, redactor)
    except RedactionUnavailable as exc:
        patterns_only = getattr(redactor, "patterns_only", None)
        if payload.classification is DataClass.PUBLIC and patterns_only is not None:
            return redact_run(payload, patterns_only())
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"the run was not recorded: {exc}",
            headers={"Retry-After": "60"},
        ) from None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_run(
    payload: RunRecordCreate,
    session: Session = Depends(get_session),
    redactor: Redactor | None = Depends(get_redactor),
) -> RunRecord:
    """Record one agent run, transcript and provenance included.

    Tenant and code revision are required. An outcome may only be supplied together with the
    scorer that produced it. When redaction is configured, the transcript is redacted before it
    is written, unless the writer already redacted it and said with what.
    """
    if redactor is not None:
        payload = _redacted(payload, redactor)
    record = to_record(payload)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.get("/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunRecord:
    """Retrieve one run."""
    record = session.get(RunRecord, run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    return record


class ProvenanceFormat(str, enum.Enum):
    PROV = "prov"
    OPENLINEAGE = "openlineage"
    ROCRATE = "rocrate"


_MEDIA_TYPE = {
    ProvenanceFormat.PROV: "application/json",
    ProvenanceFormat.OPENLINEAGE: "application/json",
    ProvenanceFormat.ROCRATE: "application/ld+json",
}


@router.get("/{run_id}/provenance")
def run_provenance(
    run_id: str,
    format: ProvenanceFormat = Query(
        ProvenanceFormat.PROV,
        description="prov: W3C PROV-JSON. openlineage: a RunEvent. rocrate: the Process Run "
        "Crate's ro-crate-metadata.json.",
    ),
    session: Session = Depends(get_session),
) -> Response:
    """One run in a provenance standard, produced by that standard's own library.

    The scorer that decided the outcome and whether its verdict may be cited travel as a
    declared extension in every format; see docs/schemas.
    """
    record = session.get(RunRecord, run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    payload = to_payload(record)
    if format is ProvenanceFormat.PROV:
        body = (
            to_prov(payload, record.run_id, record.created_at).serialize(format="json")
            or ""
        )
    elif format is ProvenanceFormat.OPENLINEAGE:
        from openlineage.client.serde import Serde

        body = Serde.to_json(to_openlineage(payload, record.run_id, record.created_at))
    else:
        with tempfile.TemporaryDirectory() as out:
            metadata = to_process_run_crate(
                payload, record.run_id, record.created_at, Path(out)
            )
            body = metadata.read_text()
    return Response(content=body, media_type=_MEDIA_TYPE[format])


@router.post("/{run_id}/approvals")
def record_approval(
    run_id: str, approval: Approval, session: Session = Depends(get_session)
) -> RunRecord:
    """Record that a person approved, refused or overrode an action of this run.

    Kept beside the run rather than in a prompt log, because human oversight is a thing an
    audit asks to see, and the answer has to be who, what and when.
    """
    record = session.get(RunRecord, run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    record.approvals = [*record.approvals, approval.model_dump()]
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.post("/{run_id}/label")
def label_run(
    run_id: str, update: LabelUpdate, session: Session = Depends(get_session)
) -> RunRecord:
    """Attach an outcome to a run.

    The source is mandatory: a label whose provenance is unknown cannot be trained on or
    cited, and a corpus that permits unattributed labels discovers this only once it is
    expensive to fix.
    """
    record = session.get(RunRecord, run_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    record.resolved = update.resolved
    record.label_source = update.label_source
    record.instrument = update.instrument
    record.degraded = update.degraded
    record.labelled_at = datetime.now(timezone.utc)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.get("/validity/report")
def validity_report(
    tenant: str = Query(..., description="Tenant whose runs to adjudicate."),
    item_prefix: str = Query("", description="Optional filter on the item key."),
    session: Session = Depends(get_session),
) -> ValidityResponse:
    """Adjudicate whether a contrast across this tenant's arms is sound enough to report.

    Read `could_have_flagged` before believing `sound`: a clean verdict over one arm, or over
    a set with no exclusions in it, is not evidence of anything.
    """
    statement = select(RunRecord).where(RunRecord.tenant == tenant)
    records = session.exec(statement).all()
    if item_prefix:
        records = [r for r in records if r.item.startswith(item_prefix)]
    observations = [
        _Observation(item=r.item, arm=r.arm, channel=r.exclusion_channel)
        for r in records
    ]
    report = check_comparison(observations)
    return ValidityResponse(
        sound=report.sound,
        could_have_flagged=report.could_have_flagged,
        summary=report.summary(),
        arms_examined=report.arms_examined,
        channels_examined=report.channels_examined,
        observations_examined=report.observations_examined,
        paired_items=report.paired_items,
        total_items=report.total_items,
        flagged=[ChannelSpreadResponse.of(c) for c in report.flagged],
    )
