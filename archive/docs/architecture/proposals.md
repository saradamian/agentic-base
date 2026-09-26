# Two attributes to propose upstream

The reuse ledger says the two facts this repository keeps having to carry as private extensions
belong in a standard other people implement. The venue exists now: the OpenTelemetry GenAI
conventions live in their own repository under the Agentic AI Foundation's umbrella, every
attribute is still Development status, and Development is the window in which proposals land.
These are written so they can be filed as issues without rewriting; filing them is a decision
for the maintainer, not for a commit.

## 1. `gen_ai.agent.configuration.fingerprint`

**Attribute.** `gen_ai.agent.configuration.fingerprint`, string, on `invoke_agent` spans.
A stable digest of everything that defines the agent's configuration for this invocation:
the enabled subsystems, the environment it exports, the budget, and the resolved versions of
the libraries whose code runs inside it.

**Why the existing attributes do not cover it.** `gen_ai.agent.name` and
`gen_ai.agent.version` name the agent; they do not say how it was configured. Two invocations
of one named agent can differ in a dozen toggles and be indistinguishable in a trace. An
evaluation that compares two configurations needs a value that changes when any of them
changes, and only when one of them changes.

**Evidence.** In one campaign of 6,880 cells, two arms whose flag dictionaries were identical
differed only in an environment export; a digest over flags alone gave them the same value,
and a cell mislabelled as one arm passed every check as the other. Later, a library the agent
imported changed behaviour under a digest that could not see library versions. Both are the
same defect: the trace could not tell two configurations apart. See
`agentic.scaffold.rung_fingerprint` in the consumer project for the digest that closed it.

**Proposed text.** "A digest that changes whenever the agent's effective configuration
changes. Producers SHOULD include enabled capabilities, environment-derived settings, budgets,
and resolved versions of components whose code executes inside the agent. Consumers MUST
treat two spans with different fingerprints as different configurations and SHOULD NOT pool
their outcomes."

## 2. `gen_ai.evaluation.authority` and `gen_ai.evaluation.degraded`

**Attributes.** On the `gen_ai.evaluation.result` event beside `gen_ai.evaluation.name` and
`gen_ai.evaluation.score.*`:

* `gen_ai.evaluation.authority`, enum `none | diagnostic | authoritative`. Whether this
  evaluation's verdict may be reported as a result, independent of what produced it.
* `gen_ai.evaluation.degraded`, boolean. Whether the evaluator returned its fail-open default
  because it could not run.

**Why the existing attributes do not cover it.** Evaluation sources are typed by modality:
human, model, code. A convenience checker and a benchmark's authoritative harness are both
code. On a measured corpus those two disagreed in both directions, with roughly a quarter of
the disagreements in the flattering direction, and their error rate differed several-fold
across arms so it did not cancel in a contrast. Modality cannot tell a reader whether a number
may be cited; authority can. And an evaluator that fails open produces a result-shaped answer
indistinguishable afterwards from one that ran, unless the event says so.

**Evidence.** 10,920 recorded outcomes in one project: 6,178 from a convenience checker, 4,742
with no evaluator named, none from the authoritative one, because attribution was optional.
A calibration run of a judge reported a clean table that was entirely fail-open defaults; it
was caught only because the verdict carried an explicit degraded flag.

**Proposed text.** "`gen_ai.evaluation.authority` states the standing of the verdict, not the
mechanism that produced it. Producers MUST set it when the verdict is intended to be reported.
`gen_ai.evaluation.degraded` MUST be true when the evaluator returned a default because it
could not complete; consumers MUST NOT report a degraded verdict as a result."

## What this repository does meanwhile

Both facts travel as declared extensions: the OpenLineage run facet in
`docs/schemas/OutcomeRunFacet.json`, the PROV agent attributes, and the Process Run Crate
property values in `agentic_base.provenance`. When either attribute lands upstream, the
extension is replaced by the standard's name and the ledger row moves from BRIDGE to ADOPT.
