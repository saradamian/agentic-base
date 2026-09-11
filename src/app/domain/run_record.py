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

from pydantic import model_validator
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
    component_versions: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    """Resolved version of every component whose change would change behaviour.

    One revision stops being enough the moment an application depends on a library that can move
    underneath it. A configuration fingerprint governs flags; it cannot see the version of imported
    code, so two runs can share a fingerprint, share a code revision, and still have run different
    software.

    That failure has a precedent worth stating: a study was protected by pinning a flag, and the
    commit that shipped the flag also rewrote the branch the flag selected between. The pin was
    real and the protection was not.

    So record what actually resolved. `{"agentic-base": "0.2.1", "agentic-env": "0.5.0"}`. A run
    that cannot name its components is placeable only by date, which is the weakest form of
    placement there is.
    """

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


class RunRecordCreate(SQLModel):
    """What a caller must supply to record a run.

    Separate from the table model on purpose. SQLModel skips validation on table classes, so a
    validator written there would look like enforcement and do nothing. Anything the platform
    genuinely refuses to accept has to be refused here.

    Two fields have no default, and the fact that this is mildly annoying is the point. Optional
    provenance is never supplied: not through laziness, but through the honest path of least
    resistance while you are trying to get one thing working. In the project this came from, a
    corpus of 12,630 outcome rows ended up with 6,842 attributed to a convenience checker, 5,788
    with no scorer named at all, and none at all attributed to the authoritative one, because
    attribution was a later step that nobody ran. A scorer cannot be assigned to a verdict after
    the fact.
    """

    tenant: str
    code_revision: str
    """The revision that produced this run. Without it the record cannot be placed against a
    later declaration that some field changed meaning, and that placement cannot be recovered."""

    component_versions: dict[str, str] = Field(default_factory=dict)
    """Resolved versions of the libraries that can change behaviour underneath this run.

    Optional rather than required, because an application with no such dependency has nothing to
    record. It stops being optional the moment one exists, and `epochs` treats a record with no
    component versions as unplaceable against a boundary declared on a component.
    """

    item: str = ""
    arm: str = ""
    arm_fingerprint: str = ""
    system_prompt: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    endpoint: str = ""
    precision: str = ""
    status: RunStatus = RunStatus.COMPLETED
    failure_kind: str = ""
    resolved: bool | None = None
    label_source: LabelSource = LabelSource.UNLABELLED
    degraded: bool = False
    instrument: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    joules: float = 0.0
    num_steps: int = 0
    total_tool_calls: int = 0
    elapsed_ms: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def an_outcome_requires_a_source(self) -> "RunRecordCreate":
        """Refuse an outcome whose scorer is not named."""
        if self.resolved is not None and self.label_source is LabelSource.UNLABELLED:
            raise ValueError(
                "resolved was supplied without a label_source. Record the run without an outcome "
                "and attach one later, or name the scorer now."
            )
        return self

    @model_validator(mode="after")
    def a_failure_kind_belongs_to_a_failure(self) -> "RunRecordCreate":
        """A detail on a completed run is a mislabelled exclusion waiting to happen."""
        if self.failure_kind and self.status is RunStatus.COMPLETED:
            raise ValueError("failure_kind was supplied on a run whose status is completed")
        return self

    def to_record(self) -> RunRecord:
        return RunRecord(**self.model_dump())
