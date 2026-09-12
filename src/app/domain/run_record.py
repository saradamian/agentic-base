"""The stored run record — one row per agent run.

This module is the *service's* persistence. The vocabulary and the rules live in
:mod:`app.domain.outcomes` and do not import a database, because a consumer must be able to take
the discipline without taking the storage. Importing this module costs you SQLModel; importing
``outcomes`` costs you nothing beyond pydantic. Consumers want the second.

A row carries three things nothing else on the platform carries:

* **the transcript the model actually received**, including the assembled system prompt, which
  is what makes a run replayable and attributable to a configuration;
* **the provenance of its outcome label** — who decided, not just what was decided;
* **the provenance of its environment** — model, endpoint, precision, code revision, and a
  fingerprint of the configuration that defines the arm.

Two fields exist because their absence cost something real and are worth naming here:

``degraded``
    Every automated verdict records whether it was produced by a working instrument. A scorer
    that fails open returns a result-shaped answer indistinguishable from a real one; this flag
    is the only thing that separates them afterwards.

``instrument``
    Which implementation actually ran. A path that silently substitutes a fallback is
    indistinguishable later from one that was chosen deliberately, and surfaces months on as
    unexplained variance between arms.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.domain.outcomes import (
    CITABLE_LABEL_SOURCES,
    EXCLUDED_STATUSES,
    Judgeable,
    LabelAuthority,
    LabelSource,
    LabelUpdate,
    RunRecordCreate,
    RunStatus,
    authority_of,
    exclusion_channel,
    is_citable,
    is_excluded,
    mlflow_source_type,
)

__all__ = [
    "CITABLE_LABEL_SOURCES",
    "EXCLUDED_STATUSES",
    "Judgeable",
    "LabelAuthority",
    "LabelSource",
    "LabelUpdate",
    "RunRecord",
    "RunRecordCreate",
    "RunStatus",
    "authority_of",
    "exclusion_channel",
    "is_citable",
    "is_excluded",
    "mlflow_source_type",
    "to_record",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# `table=True` is SQLModel's own subclass kwarg. The pydantic plugin does not model it and
# SQLModel ships no plugin of its own, so the checker sees an unknown argument to
# `__init_subclass__`. Scoped to the line rather than silenced repository-wide.
class RunRecord(SQLModel, table=True):  # type: ignore[call-arg]
    """One agent run, as stored."""

    __tablename__ = "run_record"

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    created_at: datetime = Field(default_factory=_now, index=True)

    # --- tenancy and grouping -------------------------------------------------
    tenant: str = Field(index=True, description="Owning project or research group.")
    item: str = Field(
        default="", index=True, description="What was attempted. Pairing key."
    )
    arm: str = Field(
        default="", index=True, description="Condition under which it ran."
    )
    arm_fingerprint: str = Field(
        default="",
        index=True,
        description=(
            "Digest of the configuration that defines the arm. Two runs sharing a label but "
            "not a fingerprint were not the same experiment and must never be pooled."
        ),
    )

    # --- what the model saw ---------------------------------------------------
    system_prompt: str = Field(default="")
    messages: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))

    # --- environment provenance ----------------------------------------------
    model: str = Field(default="", index=True)
    endpoint: str = Field(default="")
    precision: str = Field(default="")
    code_revision: str = Field(default="")
    component_versions: dict[str, str] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    """Resolved version of every component whose change would change behaviour.

    One revision stops being enough the moment an application depends on a library that can move
    underneath it. A configuration fingerprint governs flags; it cannot see the version of
    imported code, so two runs can share a fingerprint, share a code revision, and still have run
    different software.

    That failure has a precedent worth stating: a study was protected by pinning a flag, and the
    commit that shipped the flag also rewrote the branch the flag selected between. The pin was
    real and the protection was not.

    So record what actually resolved. A run that cannot name its components is placeable only by
    date, which is the weakest form of placement there is.
    """

    # --- outcome --------------------------------------------------------------
    status: RunStatus = Field(default=RunStatus.COMPLETED, index=True)
    failure_kind: str = Field(
        default="", description="Free-form detail behind a non-completed status."
    )
    resolved: bool | None = Field(default=None)
    label_source: LabelSource = Field(default=LabelSource.UNLABELLED, index=True)
    labelled_at: datetime | None = Field(default=None)

    # --- honesty of the measurement itself ------------------------------------
    degraded: bool = Field(
        default=False,
        description=(
            "True when any automated verdict here came from a fallback or unavailable probe."
        ),
    )
    instrument: str = Field(
        default="", description="Which implementation actually produced the verdict."
    )

    # --- cost -----------------------------------------------------------------
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    joules: float = Field(
        default=0.0,
        description=(
            "Energy attributable to this run. A separate axis from tokens and GPU-seconds: a "
            "run that spends more wall clock on the same accelerators emits no extra tokens "
            "and still costs more."
        ),
    )
    num_steps: int = Field(default=0)
    total_tool_calls: int = Field(default=0)
    elapsed_ms: float = Field(default=0.0)

    extra: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # --- derived --------------------------------------------------------------
    # Thin delegations. The rules live in `outcomes` so they apply to a consumer's own record
    # type too; these exist so callers here read naturally.
    @property
    def excluded(self) -> bool:
        """Whether this run leaves its arm's denominator."""
        return is_excluded(self)

    @property
    def exclusion_channel(self) -> str:
        """The channel by which it left, or `included`."""
        return exclusion_channel(self)

    @property
    def citable(self) -> bool:
        """Whether this run's outcome may be reported as a result."""
        return is_citable(self)


def to_record(payload: RunRecordCreate) -> RunRecord:
    """Build a stored row from a validated creation payload."""
    return RunRecord(**payload.model_dump())
