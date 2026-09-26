"""Endpoints for run records and comparison validity."""

import enum
import json
import tempfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from starlette import status

from agentic_base.auth import Access, caller_access
from agentic_base.db import get_session
from agentic_base.domain import audit
from agentic_base.domain.outcomes import DataClass
from agentic_base.domain.retention import accept_claimed_erasure, was_erased
from agentic_base.domain.run_record import (
    Approval,
    LabelUpdate,
    RunRecord,
    RunRecordCreate,
    payload_or_none,
    to_record,
)
from agentic_base.domain.validity import check_comparison, report_as_dict
from agentic_base.provenance import to_openlineage, to_process_run_crate, to_prov
from agentic_base.redaction.configured import get_redactor
from agentic_base.redaction.redact import RedactionUnavailable, Redactor, redact_run

router = APIRouter(prefix="/runs", tags=["runs"])


def _visible_run(session: Session, run_id: str, access: Access) -> RunRecord:
    """The run, or 404 when it does not exist or belongs to a tenant this caller may not use.

    The same answer for both, so a token cannot learn that another tenant's run exists.
    """
    record = session.get(RunRecord, run_id)
    if record is None or not access.allows(record.tenant):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    return record


def _commit_with_entry(session: Session, record: RunRecord, event: str) -> RunRecord:
    """Write a change and its audit entry together, or neither.

    Two writers that read the same last entry cannot both chain to it. The one that loses is told
    to retry rather than being written outside the log.
    """
    session.add(record)
    audit.append(session, record, event)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="another write to this tenant landed first; retry",
            headers={"Retry-After": "1"},
        ) from None
    session.refresh(record)
    return record


class ChannelSpreadResponse(BaseModel):
    """One exclusion channel that fell unevenly across arms."""

    channel: str
    rate_by_arm: dict[str, float]
    lowest_arm: str
    highest_arm: str
    ratio: float | None
    """Highest rate over lowest; null when the lowest arm has none, since JSON has no infinity.
    A diagnostic: the interval below is what decided."""
    absolute_difference: float
    interval_low: float
    interval_high: float
    """95% Newcombe score interval on the rate difference between the extreme arms."""
    description: str


class ArmFlowResponse(BaseModel):
    """One arm's row of the CONSORT flow: attempted, left and why, and what remains."""

    arm: str
    assessed: int
    excluded: dict[str, int]
    analysed: int
    description: str


class ValidityResponse(BaseModel):
    """The verdict, with the two fields a reader must not have to infer.

    `sound` and `could_have_flagged` are derived on the domain object and are stated
    explicitly here, because a verdict that is absent from a response reads as a pass. The
    shape is :func:`agentic_base.domain.validity.report_as_dict`, the same one MCP serves.
    """

    sound: bool
    could_have_flagged: bool
    summary: str
    arms_examined: int
    channels_examined: int
    observations_examined: int
    paired_items: int
    total_items: int
    item_sets_comparable: bool
    """False when the arms share no item keys: what one arm never attempted was not counted,
    and the arms may not be attempting the same task set."""
    flagged: list[ChannelSpreadResponse]
    inconclusive: list[ChannelSpreadResponse]
    """Channels whose interval spans zero but is too wide to call: too little data, and not
    evidence of soundness."""
    flow: list[ArmFlowResponse]
    """The per-arm accounting the verdict rests on, present whatever the verdict."""


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
    access: Access = Depends(caller_access),
) -> RunRecord:
    """Record one agent run, transcript and provenance included.

    Tenant and code revision are required. An outcome may only be supplied together with the
    scorer that produced it, and a citable scorer only through a token granted that scorer.
    When redaction is configured, the transcript is redacted before it is written, whatever the
    writer's own ``redaction`` field claims.

    A payload claiming an erasure in ``extra`` is accepted only when it carries none of what an
    erasure removes, which is what a replayed export of an erased run looks like; anything else
    is a run trying to skip retention while keeping its content, and is refused.
    """
    access.require(payload.tenant)
    access.require_label_source(payload.label_source)
    if redactor is not None:
        payload = _redacted(payload, redactor)
    record = to_record(payload)
    if was_erased(payload):
        try:
            claimed_at = accept_claimed_erasure(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from None
        record.erased_at = claimed_at or record.created_at
    return _commit_with_entry(session, record, "created")


class _ExportLine(BaseModel):
    run_id: str
    created_at: datetime
    labelled_at: datetime | None
    record: RunRecordCreate


@router.get("/export")
def export_tenant(
    tenant: str = Query(..., description="The tenant whose corpus is exported."),
    session: Session = Depends(get_session),
    access: Access = Depends(caller_access),
) -> StreamingResponse:
    """Everything recorded for one tenant, as newline-delimited JSON.

    The Data Act has applied since 12 September 2025: a customer of a data processing service may
    leave and take their data and digital assets with them. That is only true if there is a way
    out that does not go through us, so this exists and is one request.

    The first line is a manifest: the tenant, the time, how many records follow, and the schema
    they are instances of. A file that says how many records it should contain can be checked
    against itself; one that does not cannot be told apart from a truncated download. Each line
    after it is one run: its id, when it was recorded and labelled, and under `record` the run in
    the shape the write path accepts, so an export says which run and when, and can be replayed
    into another instance of this service, and `GET /runs/{id}/provenance` gives any single run in
    W3C PROV, OpenLineage or an RO-Crate for a reader that is not this service.
    """
    access.require(tenant)
    ids = list(
        session.exec(
            select(RunRecord.run_id)
            .where(RunRecord.tenant == tenant)
            .order_by(RunRecord.created_at)
        )
    )
    # Validate before the manifest is written: a row that no longer passes the creation rules
    # is skipped with a warning, and the count must say what actually follows, or the file
    # reads as a truncated download.
    exportable = [
        run_id
        for run_id in ids
        if (record := session.get(RunRecord, run_id)) is not None
        and payload_or_none(record) is not None
    ]
    manifest = {
        "tenant": tenant,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "records": len(exportable),
        "format": "application/x-ndjson",
        "schema": "agentic_base.domain.outcomes.RunRecordCreate",
        "note": "one run per line after this one: run_id, created_at and labelled_at, "
        "and under record the run in the shape POST /runs accepts",
    }

    def lines() -> Iterator[str]:
        yield json.dumps(manifest) + "\n"
        for run_id in exportable:
            record = session.get(RunRecord, run_id)
            if record is None:
                continue
            payload = payload_or_none(record)
            if payload is None:
                continue
            yield (
                _ExportLine(
                    run_id=record.run_id,
                    created_at=record.created_at,
                    labelled_at=record.labelled_at,
                    record=payload,
                ).model_dump_json()
                + "\n"
            )

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{tenant}-runs.ndjson"',
            "X-Record-Count": str(len(exportable)),
        },
    )


class IntegrityResponse(BaseModel):
    """Whether a tenant's records are as the service wrote them, and what was verified."""

    tenant: str
    intact: bool
    could_have_failed: bool
    entries_checked: int
    runs_checked: int
    head_seq: int | None
    """The chain position the service last recorded for this tenant; null when it never did."""
    first_broken_entry: int | None
    altered_runs: list[str]
    unchained_runs: list[str]
    orphaned_entries: list[str]
    """Runs the log describes whose row is gone."""
    erased_runs: list[str]
    """Runs whose personal fields the service erased: reported, not a failure."""
    summary: str


@router.get("/integrity")
def integrity(
    tenant: str = Query(..., description="The tenant whose records to verify."),
    session: Session = Depends(get_session),
    access: Access = Depends(caller_access),
) -> IntegrityResponse:
    """Recompute the tenant's audit log and compare it, both ways, against the run rows.

    Read `could_have_failed` before believing `intact`: a tenant with no runs verifies trivially.
    This detects an edit by anyone who does not rewrite the whole log, its head included; it is
    not a signature.
    """
    access.require(tenant)
    verdict = audit.verify(session, tenant)
    return IntegrityResponse(
        tenant=tenant,
        intact=verdict.intact,
        could_have_failed=verdict.could_have_failed,
        entries_checked=verdict.chain.records_checked,
        runs_checked=verdict.runs_checked,
        head_seq=verdict.head_seq,
        first_broken_entry=verdict.chain.first_broken_index,
        altered_runs=verdict.altered,
        unchained_runs=verdict.unchained,
        orphaned_entries=verdict.orphaned,
        erased_runs=verdict.erased,
        summary=verdict.summary(),
    )


@router.get("/{run_id}")
def get_run(
    run_id: str,
    session: Session = Depends(get_session),
    access: Access = Depends(caller_access),
) -> RunRecord:
    """Retrieve one run."""
    return _visible_run(session, run_id, access)


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
    access: Access = Depends(caller_access),
) -> Response:
    """One run in a provenance standard, produced by that standard's own library.

    The scorer that decided the outcome and whether its verdict may be cited travel as a
    declared extension in every format; see docs/schemas.
    """
    record = _visible_run(session, run_id, access)
    payload = payload_or_none(record)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"run {run_id} does not pass the rules POST /runs enforces, so no provenance "
                "can be emitted for it. Attach a label that names its scorer, then ask again."
            ),
        )
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
    run_id: str,
    approval: Approval,
    session: Session = Depends(get_session),
    access: Access = Depends(caller_access),
) -> RunRecord:
    """Record that a person approved, refused or overrode an action of this run.

    Kept beside the run rather than in a prompt log, because human oversight is a thing an
    audit asks to see, and the answer has to be who, what and when.
    """
    record = _visible_run(session, run_id, access)
    record.approvals = [*record.approvals, approval.model_dump()]
    return _commit_with_entry(session, record, "approved")


@router.post("/{run_id}/label")
def label_run(
    run_id: str,
    update: LabelUpdate,
    session: Session = Depends(get_session),
    access: Access = Depends(caller_access),
) -> RunRecord:
    """Attach an outcome to a run.

    The source is mandatory: a label whose provenance is unknown cannot be trained on or
    cited, and a corpus that permits unattributed labels discovers this only once it is
    expensive to fix. A citable source is only accepted from a token granted that scorer.
    """
    record = _visible_run(session, run_id, access)
    access.require_label_source(update.label_source)
    record.resolved = update.resolved
    record.label_source = update.label_source
    record.instrument = update.instrument
    record.degraded = update.degraded
    record.labelled_at = datetime.now(timezone.utc)
    return _commit_with_entry(session, record, "labelled")


@router.get("/validity/report")
def validity_report(
    tenant: str = Query(..., description="Tenant whose runs to adjudicate."),
    item_prefix: str = Query("", description="Optional filter on the item key."),
    session: Session = Depends(get_session),
    access: Access = Depends(caller_access),
) -> ValidityResponse:
    """Adjudicate whether a contrast across this tenant's arms is sound enough to report.

    Read `could_have_flagged` before believing `sound`: a clean verdict over one arm, or over
    a set with no exclusions in it, is not evidence of anything.
    """
    access.require(tenant)
    statement = select(RunRecord).where(RunRecord.tenant == tenant)
    records = session.exec(statement).all()
    if item_prefix:
        records = [r for r in records if r.item.startswith(item_prefix)]
    return ValidityResponse.model_validate(report_as_dict(check_comparison(records)))
