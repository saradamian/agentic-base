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
| the run record, with the system prompt the model actually received | `app.domain.run_record.RunRecord` |
| outcome-label provenance | `label_source`, with `CITABLE_LABEL_SOURCES` making the distinction structural, not advisory |
| the degraded flag on automated verdicts | `RunRecord.degraded`, and `citable` refuses a degraded verdict from any source |
| which instrument actually ran | `RunRecord.instrument` |
| configuration fingerprinting for an arm | `RunRecord.arm_fingerprint`, so two runs sharing a label but not a configuration can never be pooled |
| exclusion channels as first-class data | `RunStatus`, `EXCLUDED_STATUSES`, `exclusion_channel` |
| arm-correlated missingness detection | `app.domain.validity` |
| energy as an axis beside tokens | `RunRecord.joules` |
| free-form join keys with no core vocabulary | `RunRecord.extra` |

## Left out

Each of these was measured, and the measurement is the reason.

| what | why |
|---|---|
| **the agent framework itself** | the layer is not the product. Applications bring their own agent |
| **the skill library** | its effect on task success has never been measured. Shipping it transfers a maintenance cost for an unproven benefit, and the recipient inherits the obligation to defend it. What it taught is here instead, as three design rules below |
| **auto-generated executable "skills"** | a population of callable tools whose body was a list of tool names and a function returning it: a surface advertising execution and delivering a plan |
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
