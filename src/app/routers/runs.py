"""Endpoints for run records and comparison validity."""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette import status

from app.db import get_session
from app.domain.run_record import LabelUpdate, RunRecord, RunRecordCreate
from app.domain.validity import ChannelSpread, check_comparison

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


@router.post("", status_code=status.HTTP_201_CREATED)
def create_run(payload: RunRecordCreate, session: Session = Depends(get_session)) -> RunRecord:
    """Record one agent run, transcript and provenance included.

    Tenant and code revision are required. An outcome may only be supplied together with the
    scorer that produced it.
    """
    record = payload.to_record()
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.get("/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunRecord:
    """Retrieve one run."""
    record = session.get(RunRecord, run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    record.resolved = update.resolved
    record.label_source = update.label_source
    record.instrument = update.instrument
    record.degraded = update.degraded
    record.labelled_at = datetime.now(UTC)
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
        _Observation(item=r.item, arm=r.arm, channel=r.exclusion_channel) for r in records
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
