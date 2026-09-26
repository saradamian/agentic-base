# Concepts

The fifteen terms the code and the rest of these pages use. Each names the field or function it
refers to, so you can look it up.

## The two checks

**Arm and item.** An *arm* is one configuration being compared: a model, a prompt, a version of an
agent. An *item* is one unit of work that every arm attempts: a task, a question, an issue. A
record that compares nothing leaves both empty.

**Exclusion channel.** Every way a run can leave the denominator before it gets a verdict: a
timeout, a crash, an error, a limit, a record with no verdict (`no_verdict`), a task an arm never
started (`never_attempted`, see `agentic_base.domain.validity`). The check counts each channel per
arm. A run that is counted is `included`.

**Sound, not sound, inconclusive.** What `check_comparison` returns. *Not sound* means some
exclusion channel's rate differs between arms by more than a 95% interval and an absolute floor
allow, so a resolve rate computed over the survivors compares different populations. *Inconclusive*
means there is too little data for the interval to decide. *Sound* means neither.

**Could have flagged.** Whether the check was able to fail on this input. With one arm, or with no
exclusion anywhere, a clean result means nothing, and `agentic-base check` exits 2 rather than 0.

**Scorer.** Who decided a run's outcome: the benchmark's own harness, a person, the agent itself,
another model, the user's thumbs-up. Stored as `label_source` (`agentic_base.domain.outcomes.LabelSource`).
An outcome with no scorer is refused by the service.

**Citable and diagnostic.** A scorer's standing (`LabelAuthority`). Only the benchmark's own
harness or grader and a person are *citable*; everything else is *diagnostic*: worth recording,
not worth reporting as a result. A citable scorer that failed open is marked *degraded* and loses
its standing for that run.

## The record

**Run record.** One agent run as the service stores it: what the model received, the environment
it ran in, the outcome and who scored it. Only the tenant and the code revision are required.

**Tenant.** The team or project a record belongs to. Every data request names one, and a token
reaches only the tenants listed for it in `API_TOKENS`.

**Principal.** The person or system the run acted for, kept as an identifier (`principal`).

**Data class and isolation tier.** What class of data the run touched (`DataClass`: public,
internal, confidential, personal, health) and the platform tier it ran on (`IsolationTier`:
community, virtualised, isolated). A personal or health run on the community tier is refused.

**Disclosure.** How the person was told they were dealing with an AI (`disclosure`), as the AI Act
asks. `"none"` is a valid and visible answer.

**Approval.** A person said yes to an action the agent wanted to take (`Approval`): who, what, and
when, kept beside the run.

**Audit chain.** Every create, label and approval is appended to a per-tenant hash chain.
`GET /runs/integrity` verifies it and names a changed, cut or missing entry.

**Redaction.** Removing personal data and credentials from a transcript before it is written
(`agentic_base.redaction`). When redaction is configured and cannot run, the write is refused
rather than stored unredacted.

**Erasure.** Emptying a person's transcript and names on request or after a tenant's retention
period, while the audit chain still verifies and reports that the erasure happened.
