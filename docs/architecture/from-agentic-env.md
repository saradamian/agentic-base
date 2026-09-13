# What came from agentic-env, and what stayed there

`agentic-env` stays the experimentation environment, where things get tried and measured. This
project is the production layer, and it starts from an empty repository.

The governing rule of the extraction:

> **Take the measurements and the guards, not the subsystems.**

Subsystems are a few hundred lines each and cheap to rebuild. The measurements cost days apiece and
are the only thing that stops a rebuild reproducing a year of mistakes.

## Taken

| what | shape here |
|---|---|
| the run record, with the system prompt the model actually received | `agentic_base.domain.run_record.RunRecord` |
| outcome-label provenance | `label_source`, with `CITABLE_LABEL_SOURCES` making the distinction structural, not advisory |
| the degraded flag on automated verdicts | `RunRecord.degraded`, and `citable` refuses a degraded verdict from any source |
| which instrument actually ran | `RunRecord.instrument` |
| configuration fingerprinting for an arm | `RunRecord.arm_fingerprint`, so two runs sharing a label but not a configuration can never be pooled |
| exclusion channels as first-class data | `RunStatus`, `EXCLUDED_STATUSES`, `exclusion_channel` |
| arm-correlated missingness detection | `agentic_base.domain.validity` |
| energy as an axis beside tokens | `RunRecord.joules` |
| free-form join keys with no core vocabulary | `RunRecord.extra` |
| the job-result protocol over batch stdout | `agentic_base.hpc.job_result`, with the consumer's markers as parameters |
| the outbound URL check with DNS pinning | `agentic_base.security.netsec` |
| the structural pre-filter on generated code | `agentic_base.code_policy` |
| the completion probe that asks for an answer, not a status | `agentic_base.llm.health` |
| the span vocabulary, from the standard packages | `agentic_base.observability.conventions` |
| limits resolved when read, not at import | `agentic_base.limits` |
| the tool contract | `agentic_base.tools.types` |
| the curated MCP surface and the recording seam | `agentic_base.mcp.server`, `agentic_base.recording` |
| the provenance emitters, on the standards' own libraries | `agentic_base.provenance`, with the scorer and its authority as a declared extension |

## What has moved back, as imports

agentic-env imports four things from here and has deleted its copy of each: the job-result
protocol, with its own marker lines passed as parameters; the span vocabulary, which a test there
holds to being read rather than restated; the provenance documents, which it extends through the
standards' own libraries with the agents, prompt, inputs and content-addressed artifacts only it
knows; and the MCP transport, which is the official SDK on both sides. It records the installed
version of this layer beside every run and refuses to pool runs across a version no epoch
declares, so a release here that changes behaviour cannot be mistaken for the same software.

## Left out

Each of these was measured, and the measurement is the reason.

| what | why |
|---|---|
| **the agent framework itself** | the layer is not the product. Applications bring their own agent |
| **the skill library** | measured. Of the artifacts its minting loop produced, one is in demonstrable use, and nothing it has ever made cleared promotion: all eleven entries in the shared tier match a human-authored file on disk. Injection of a hand-written skill is a different question and was ablated separately: a null mean over five paired tasks, with two large moves in opposite directions and an identified cause on each side |
| **auto-generated executable "skills"** | seven were minted and none was ever dispatched. One body is its own source skill as a string literal with no logic, so the surface advertises execution and returns a copy. A second generator mined tool-name sequences: five minted, none dispatched, and it discards arguments, so it cannot tell reading two files from retrying one read |
| **tree search over reasoning paths** | ran degenerate for an entire campaign because its evaluator defaulted off. A layer whose default configuration does not do the thing the layer is named for is a trap |
| **read-reject steering** | measured costing several points of task success and buying nothing, by making runs finish empty-handed three to four times more often |
| **execution-grounded number verification** | a measured negative: the model echoes its own claim in the check it generates |
| **our own span and trace types** | OpenTelemetry is the standard and was already a dependency |
| **our own metrics exposition** | `prometheus_client` and the platform's Prometheus |
| **SQLite as the storage tier** | correct for a single-workstation experiment, wrong for a multi-tenant service. PostgreSQL is a tenant resource |
| **our own atomic-write and locking helpers** | a database has transactions |
| **our own configuration layering** | `pydantic-settings`, which the template already uses |
| **twelve product packages** | the domain-agnostic core was the good idea. The products are not the layer |

## Three rules the skill library paid for

They cost a flood of useless entries and two months of unprunable rows, so they are stated as rules,
not as code to copy.

These numbers come from a measurement of our own library by another session on 2026-09-10, read
at source rather than relayed. The reason to state them instead of "unmeasured" is that
"unmeasured" is an invitation: a later reader can reopen a settled decision with "nobody checked,
let us try". Numbers close that.

1. **Counters are born at zero, with their denominator.** Ours were seeded from how often a pattern
   had been *observed* and recorded that as a success rate, while pruning only reached entries below
   a floor. Every such entry was therefore born perfect, never invoked, and unprunable by
   construction.
2. **Retrieval normalises by query length, never by entry length.** Normalise by the entry and thin
   entries outrank the substantial ones they duplicate, self-reinforcingly, because the thin one is
   a better ratio. That is the entire incentive structure of a shared store.
3. **Promotion needs an explicit eligibility class, not a confidence threshold.** A confidence gate
   promotes documentation precisely because documentation is confident.

And one that only appears at multi-tenant scale: **never merge across tenants, link.** Within one
tenant, a crowd of near-identical entries is waste. Across tenants it is two groups independently
arriving at the same practice, which is the most valuable signal such a store can produce. Merging
it destroys the finding the store exists to get.

## The verification discipline that came with them

- A guard that cannot fail is worse than no guard, because it gets cited. `tests/domain/test_validity.py`
  opens with a positive control, and that control has been confirmed to fail when the detector is
  disabled, not assumed to.
- Before believing an absence, check the reader could have produced a presence. `ValidityReport`
  therefore reports how many arms, channels and observations it examined, and `could_have_flagged`
  is a field, not something a reader has to infer.
- State whether a number was measured, derived, or guessed. A guessed expected value is an untested
  assertion, not a reference.

## What the first import found did not fit

Recorded here because the first consumer was expected to falsify more of the design than another
month of guards would, and it should be visible whether it did. It did, six times.

**The markers.** `agentic-env` adopted this protocol before this package existed and its jobs
print `###AGENTIC_JOB_RESULT_START###`. A reader that knew only our marker would have reported
every one of those results absent, which is the failure the third state exists to prevent, one
layer up. `parse_result` and `encode_result` take the markers as parameters; the default is the
protocol and the parameter is the migration.

**The decoder.** Ours joined every line inside the block and decoded the result, so a log line
from another rank landing inside the block turned a correctly printed result into a corrupt one.
That is the case the protocol exists for, and the consumer's decoder already handled it by trying
each line and taking the one that decodes. The consumer's behaviour was the measured one, so it
is now ours.

**The wording.** The consumer's tests read two substrings of the corrupt detail. The base's
wording was changed to carry them, and lost twice to the auto-merge race; the consumer loosened
its assertions to what both wordings share. Message text is not a contract.

**A run id is not always a UUID.** OpenLineage requires one; the consumer keys runs by an integer.
The base derives a stable UUID and carries the original id in the facet, so three emitters agree
on one rule.

**A benchmark's own grader had no label source.** tau, Terminal-Bench and ARE ship a grader and
no separate harness. `benchmark_grader` is authoritative and citable, named apart from the
SWE-bench harness so nobody assumes its calibration.

**The crate was written before it could be extended.** The consumer wants to fold its own
entities, the files a run produced, onto the base's document. `build_process_run_crate` now
returns the unwritten crate; the writer calls it.
