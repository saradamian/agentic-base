"""Run records — the audit and training substrate.

One row per agent run, written at the moment the run happens rather than reconstructed
afterwards. It carries three things nothing else on the platform carries:

* **the transcript the model actually received**, including the assembled system prompt, which
  is what makes a run replayable and attributable to a configuration;
* **the provenance of its outcome label** — who decided, not just what was decided;
* **the provenance of its environment** — model, endpoint, precision, code revision, and a
  fingerprint of the configuration that defines the arm.

Four field-level decisions, each of which exists because its absence cost something real:

``label_source``
    Not all scorers are equal. Two scorers on the same artifact can disagree in both
    directions, and a corpus where a third of the rows cannot name their own scorer cannot be
    trained on or cited. Labelling is therefore impossible without declaring a source.

``degraded``
    Every automated verdict records whether it was produced by a working instrument. A scorer
    that fails open returns a result-shaped answer indistinguishable from a real one; this flag
    is the only thing that separates them afterwards.

``instrument``
    Which implementation actually ran. A path that silently substitutes a fallback is
    indistinguishable later from one that was chosen deliberately, and surfaces months on as
    unexplained variance between arms.

``extra``
    The core carries mechanism and no vocabulary. Applications put their own join keys here,
    which is what lets a run be joined to an external scorer without parsing its prompt.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class LabelSource(str, enum.Enum):
    """Who decided this run's outcome."""

    UNLABELLED = "unlabelled"
    SELF_REPORTED = "self_reported"
    """The agent's own claim. Never citable; an agent grading itself is not a measurement."""

    CONVENIENCE_VERIFIER = "convenience_verifier"
    """An in-tree check. Useful as a diagnostic, not as a score: such checks have been
    measured erring at rates that differ several-fold across arms, which does not cancel in a
    contrast."""

    OFFICIAL_HARNESS = "official_harness"
    """The benchmark's own authoritative scorer."""

    HUMAN = "human"


CITABLE_LABEL_SOURCES = frozenset({LabelSource.OFFICIAL_HARNESS, LabelSource.HUMAN})
"""Sources whose labels may be reported as results. Everything else is a diagnostic."""


class RunStatus(str, enum.Enum):
    """Terminal disposition of the run itself, independent of its outcome label."""

    COMPLETED = "completed"
    FAILED = "failed"
    """The agent ran and did not succeed. A measurement."""

    INFRASTRUCTURE_ERROR = "infrastructure_error"
    """Something outside the agent broke. Not a measurement; excluded, and the exclusion is
    counted per arm."""

    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


EXCLUDED_STATUSES = frozenset(
    {RunStatus.INFRASTRUCTURE_ERROR, RunStatus.TIMEOUT, RunStatus.CANCELLED}
)
"""Statuses that remove a run from its arm's denominator. Each is an exclusion channel whose
per-arm rate must be checked before any contrast is reported."""


def _now() -> datetime:
    return datetime.now(UTC)


class RunRecord(SQLModel, table=True):
    """One agent run."""

    __tablename__ = "run_record"

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    created_at: datetime = Field(default_factory=_now, index=True)

    # --- tenancy and grouping -------------------------------------------------
    tenant: str = Field(index=True, description="Owning project or research group.")
    item: str = Field(default="", index=True, description="What was attempted. Pairing key.")
    arm: str = Field(default="", index=True, description="Condition under which it ran.")
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

    # --- outcome --------------------------------------------------------------
    status: RunStatus = Field(default=RunStatus.COMPLETED, index=True)
    failure_kind: str = Field(default="", description="Free-form detail behind a non-completed status.")
    resolved: bool | None = Field(default=None)
    label_source: LabelSource = Field(default=LabelSource.UNLABELLED, index=True)
    labelled_at: datetime | None = Field(default=None)

    # --- honesty of the measurement itself ------------------------------------
    degraded: bool = Field(
        default=False,
        description="True when any automated verdict here came from a fallback or unavailable probe.",
    )
    instrument: str = Field(default="", description="Which implementation actually produced the verdict.")

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
    @property
    def excluded(self) -> bool:
        """Whether this run leaves its arm's denominator."""
        return self.status in EXCLUDED_STATUSES

    @property
    def exclusion_channel(self) -> str:
        """The channel by which it left, or `included`."""
        if not self.excluded:
            return "included"
        return self.failure_kind or self.status.value

    @property
    def citable(self) -> bool:
        """Whether this run's outcome may be reported as a result.

        Requires a label, from a citable source, produced by an instrument that was working.
        """
        return (
            self.resolved is not None
            and self.label_source in CITABLE_LABEL_SOURCES
            and not self.degraded
        )


class LabelUpdate(SQLModel):
    """Back-fill an outcome. `label_source` is mandatory by construction."""

    resolved: bool
    label_source: LabelSource
    instrument: str = ""
    degraded: bool = False
