"""Outcome vocabulary and the rules that read it.

Split out of ``run_record`` so that a consumer can adopt the *discipline* without adopting our
*storage*. The table in ``run_record`` is one implementation of a record; `agentic-env` already
has its own, holds it in SQLite inside task containers, and is not going to exchange it for a
Postgres model. If applying these rules required our table, the rules would not travel, and a
base layer whose contribution does not travel is a second copy of the code it meant to replace.

So everything here is either a value or a function over a structural protocol. Anything with a
``status``, a ``resolved`` and a ``label_source`` can be judged by it.

On the vocabulary itself. MLflow's assessment model already records who produced a judgement,
typed as human, LLM judge, or code, and attaches it to the trace. That is the same instinct and
it arrived first, so this is not a new idea and should not be presented as one. Two things it
does not do:

* Its taxonomy separates judgements by *modality*. A convenience checker and the benchmark's own
  authoritative harness are both ``CODE`` to it, and those two disagreed on a measured corpus in
  both directions, with the flattering direction accounting for roughly a quarter of the
  disagreements. Modality does not tell you whether a number may be cited. Authority does.
* Its source field is optional and additive, and an optional provenance field is not supplied.
  That second half is an argument by analogy and must be stated as one: **MLflow did not produce
  the corpus below.** We ran the experiment on ourselves, with our own optional field, and across
  33 trace stores holding 10,920 outcomes 4,742 named no scorer and not one named the
  authoritative one. Forty-three percent empty is what optional provenance looks like at scale
  rather than a failure of diligence, and nothing about that mechanism is specific to our
  implementation of it.

Hence :class:`LabelAuthority`, which is the axis MLflow lacks, and a create model that refuses
the write. ``mlflow_source_type`` maps our vocabulary onto theirs so a record can be exported
into their schema without inventing a private dialect.
"""

from __future__ import annotations

import enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


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
    """The benchmark's own authoritative scorer, published as such: the SWE-bench harness."""

    BENCHMARK_GRADER = "benchmark_grader"
    """A benchmark's own grader where the benchmark ships no separate harness: a tau environment
    reward, a Terminal-Bench grader, an ARE validator. Authoritative for that benchmark, and
    named apart from the harness because a reader must not assume the SWE-bench calibration."""

    HUMAN = "human"


CITABLE_LABEL_SOURCES = frozenset(
    {LabelSource.OFFICIAL_HARNESS, LabelSource.BENCHMARK_GRADER, LabelSource.HUMAN}
)
"""Sources whose labels may be reported as results. Everything else is a diagnostic."""


class LabelAuthority(str, enum.Enum):
    """Whether a judgement may be cited, independent of what produced it.

    The axis a modality taxonomy cannot express. Two scorers that are both code, run on the same
    artifact, can disagree in both directions; which of them a result may quote is a property of
    their standing, not of their implementation.
    """

    NONE = "none"
    DIAGNOSTIC = "diagnostic"
    """Informative, and not reportable. A floor for a single arm at best, never a contrast."""

    AUTHORITATIVE = "authoritative"


_AUTHORITY: dict[LabelSource, LabelAuthority] = {
    LabelSource.UNLABELLED: LabelAuthority.NONE,
    LabelSource.SELF_REPORTED: LabelAuthority.DIAGNOSTIC,
    LabelSource.CONVENIENCE_VERIFIER: LabelAuthority.DIAGNOSTIC,
    LabelSource.OFFICIAL_HARNESS: LabelAuthority.AUTHORITATIVE,
    LabelSource.BENCHMARK_GRADER: LabelAuthority.AUTHORITATIVE,
    LabelSource.HUMAN: LabelAuthority.AUTHORITATIVE,
}

_MLFLOW_SOURCE_TYPE: dict[LabelSource, str] = {
    LabelSource.UNLABELLED: "CODE",
    LabelSource.SELF_REPORTED: "LLM_JUDGE",
    LabelSource.CONVENIENCE_VERIFIER: "CODE",
    LabelSource.OFFICIAL_HARNESS: "CODE",
    LabelSource.BENCHMARK_GRADER: "CODE",
    LabelSource.HUMAN: "HUMAN",
}


def authority_of(source: LabelSource) -> LabelAuthority:
    """The standing of a label from this source."""
    return _AUTHORITY[source]


def mlflow_source_type(source: LabelSource) -> str:
    """The MLflow assessment source type this maps onto.

    Three of our five sources collapse to ``CODE`` there, which is exactly the information loss
    :class:`LabelAuthority` exists to carry. Export through this, and carry the authority beside
    it as metadata, rather than minting a private vocabulary for something a standard already
    names.
    """
    return _MLFLOW_SOURCE_TYPE[source]


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


@runtime_checkable
class Judgeable(Protocol):
    """What the rules below need from a record, and nothing more.

    Structural on purpose. A consumer keeps its own row type and still gets the rules.
    """

    @property
    def status(self) -> RunStatus: ...

    @property
    def failure_kind(self) -> str: ...

    @property
    def resolved(self) -> bool | None: ...

    @property
    def label_source(self) -> LabelSource: ...

    @property
    def degraded(self) -> bool: ...


def is_excluded(record: Judgeable) -> bool:
    """Whether this run leaves its arm's denominator."""
    return record.status in EXCLUDED_STATUSES


def exclusion_channel(record: Judgeable) -> str:
    """The channel by which it left, or ``included``."""
    if not is_excluded(record):
        return "included"
    return record.failure_kind or record.status.value


def is_citable(record: Judgeable) -> bool:
    """Whether this run's outcome may be reported as a result.

    Requires a label, from a source with authority, produced by an instrument that was working.
    The third clause is the one people drop: a scorer that failed open returns a result-shaped
    answer, and without the flag it is indistinguishable afterwards from one that ran.
    """
    return (
        record.resolved is not None
        and authority_of(record.label_source) is LabelAuthority.AUTHORITATIVE
        and not record.degraded
    )


class DataClass(str, enum.Enum):
    """What class of data a run touched. Set per tenant or per run, never by the agent.

    The level selects the isolation tier, the logging depth and the retention; that is the rule
    the healthcare advice asked for and it can only be applied if the class is recorded.
    """

    UNCLASSIFIED = "unclassified"
    """Not stated. Its own population: a reader must not assume it means public."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PERSONAL = "personal"
    """Personal data under the GDPR."""

    HEALTH = "health"
    """Personal health data. NEN 7510 territory if the platform processes it itself."""


class IsolationTier(str, enum.Enum):
    """The platform's isolation tier the run executed under."""

    UNSPECIFIED = "unspecified"
    COMMUNITY = "community"
    VIRTUALISED = "virtualised"
    ISOLATED = "isolated"


SENSITIVE_CLASSES = frozenset({DataClass.PERSONAL, DataClass.HEALTH})
"""Classes that may not run on the community tier."""


class Approval(BaseModel):
    """A person said yes to an action, and the record keeps that beside the run.

    Human oversight under the AI Act and the evidence NIS2 asks for are this: not a prompt that
    was shown, but who decided what, when.
    """

    action: str
    """What was approved: a repository write, a job submission, a message sent for someone."""

    decision: str
    """approved, refused, or overridden."""

    by: str
    """The person's identity, as the federation names it."""

    at: str
    """When, ISO 8601."""

    note: str = ""


class LabelUpdate(BaseModel):
    """Back-fill an outcome. ``label_source`` is mandatory by construction."""

    resolved: bool
    label_source: LabelSource
    instrument: str = ""
    degraded: bool = False


class RunRecordCreate(BaseModel):
    """What a caller must supply to record a run.

    Separate from the table model on purpose, and a plain model rather than a table one. SQLModel
    skips validation on table classes, so a validator written there would look like enforcement
    and do nothing. Anything the platform genuinely refuses to accept has to be refused here.

    Two fields have no default, and the fact that this is mildly annoying is the point. Optional
    provenance is never supplied: not through laziness, but through the honest path of least
    resistance while you are trying to get one thing working. Measured across every trace store
    of the project this came from, 10,920 recorded outcomes carried 6,178 attributed to a
    convenience checker, 4,742 attributed to nothing at all, and none attributed to the
    authoritative one, because attribution was a later step that nobody ran. A scorer cannot be
    assigned to a verdict after the fact.
    """

    tenant: str
    code_revision: str
    """The revision that produced this run. Without it the record cannot be placed against a
    later declaration that some field changed meaning, and that placement cannot be recovered."""

    component_versions: dict[str, str] = Field(default_factory=dict)
    """Resolved versions of the libraries that can change behaviour underneath this run.

    Optional rather than required, because an application with no such dependency has nothing to
    record. It stops being optional the moment one exists, and ``epochs`` treats a record with no
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
    principal: str = ""
    """The person the run acted for, as the federation names them. Empty means a service identity,
    which every block will refuse once credentials are delegated; until then it is recorded so
    the corpus can say which runs predate that."""

    classification: DataClass = DataClass.UNCLASSIFIED
    isolation_tier: IsolationTier = IsolationTier.UNSPECIFIED
    redaction: str = "none"
    """What removed personal data from the transcript before it was written: ``none``, or the
    instrument's name and version. A transcript with ``none`` and a personal classification is
    a finding, not a default."""

    approvals: list[Approval] = Field(default_factory=list)
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
    def an_outcome_requires_a_source(self) -> RunRecordCreate:
        """Refuse an outcome whose scorer is not named."""
        if self.resolved is not None and self.label_source is LabelSource.UNLABELLED:
            raise ValueError(
                "resolved was supplied without a label_source. Record the run without an "
                "outcome and attach one later, or name the scorer now."
            )
        return self

    @model_validator(mode="after")
    def sensitive_data_does_not_run_on_the_community_tier(self) -> RunRecordCreate:
        """Classification decides the tier. A run that says it touched personal or health data
        and ran on the shared tier is refused, because that is the one combination no regime
        permits. An unspecified tier passes: unknown is not the same as wrong."""
        if (
            self.classification in SENSITIVE_CLASSES
            and self.isolation_tier is IsolationTier.COMMUNITY
        ):
            raise ValueError(
                f"a run classified {self.classification.value} cannot have run on the "
                "community isolation tier"
            )
        return self

    @model_validator(mode="after")
    def a_failure_kind_belongs_to_a_failure(self) -> RunRecordCreate:
        """A detail on a completed run is a mislabelled exclusion waiting to happen."""
        if self.failure_kind and self.status is RunStatus.COMPLETED:
            raise ValueError(
                "failure_kind was supplied on a run whose status is completed"
            )
        return self
