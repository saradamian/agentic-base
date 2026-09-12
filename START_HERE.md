# Start here

Three pages, then the code. There is no larger specification behind this.

## What the service does

It is a system of record for agent runs, and a referee for claims made from that record.

You post a run. The service stores what the model received, the environment it ran in, and a
fingerprint of the configuration. You attach an outcome later, and the service refuses it unless
you name who decided. It tells you whether a comparison between two configurations is sound. It
hash-chains records so a later edit is detectable. It serves a run in W3C PROV, OpenLineage or a
Process Run Crate, exports it to MLflow, and exposes the corpus read-only over MCP so someone in a
chat client can ask.

That is all of it. It does not run agents, serve models, schedule jobs or train.

## What the library gives a consumer

Anything that imports `agentic_base` gets the rules without the storage: the outcome vocabulary
and the citability rules over a structural protocol, the validity check, the epoch declarations,
the job-result protocol for batch jobs, the outbound URL check, the code pre-filter, the span
vocabulary, and the provenance emitters. It installs on Python 3.10 with four dependencies. The
service is an optional extra.

## Who it is for

Three consumers exist, and requirements come from them.

agentic-env runs the experiments. It imported its first module from here on 2026-09-12 and is
replacing its own copies of the span vocabulary, the provenance emitters and the MCP transport
with imports.

Willma serves models. Anything here about inference points at Willma.

AI4Science submits and orchestrates jobs on Slurm. It already runs agent jobs through a template
script on a shared filesystem. Replacing that seam with an interface is the first piece of work
that helps both sides.

The AI Factory is buying a machine whose functional architecture has three verbs and no plane for
observing or evaluating anything. Its own service catalogue marks the relevant rows as partial or
absent.

## Why it is shaped this way

Most experiment tooling stores what a run produced. Almost none of it stores who decided the run
was correct, or whether the thing that decided was working at the time. None of it tells you a
comparison is invalid. That gap is why this exists, and it closes only if the refusals are in the
write path from the first day. Provenance cannot be added to runs that did not record it.

## Where this sits

`docs/architecture/blocks.md` is the design: this repository is the contracts layer under a set of
capability blocks, one per SURF system, each in its own package with the system's owner. No block
lives here. `docs/architecture/cross-cutting.md` says where logging, security, safety and
compliance live, and what the regimes ask of an agent platform.

## Read these, in this order

1. `docs/decisions.md`. Ten decisions, each cheap now and expensive later. D5 says why two
   arguments have no default. D10 says why no block is in this repository.
2. `docs/architecture/reuse-ledger.md`. What is adopted and from where. Most of what a platform
   needs already exists inside SURF, and a test holds the code to the ledger.
3. `docs/architecture/operational-traps.md`. Failures that are invisible in code review. Several
   apply to code that is not in this repository.
4. `tests/lessons/`. One test file, forty lines, no framework. It shows how a retrieval bug makes
   a measurement return a clean zero that reads like a finding.

## What is dormant

These are here because they were cheap to write while the context was fresh. They answer
questions nobody has asked yet. Do not build on them.

- The hash chain, and the AI Act and NIS2 evidence mapping. Real obligations, no users yet.
- The energy column. It is a real axis when you are billed for an allocation, and it will be zero
  here for a long time. A column that is always zero teaches people to ignore columns.
- The Snellius and LUMI profiles. Worked examples of what a cluster profile has to carry, not a
  statement that HPC is the destination.

## The first useful thing to do

Instrument something you already have. `src/agentic_base/client.py` is about ten lines at the
call site. Record twenty runs of anything, label half, and ask for the validity report. You will
find out quickly whether the required fields are in the right places.

## The habit that matters most

A guard that cannot fail is worse than no guard, because it gets cited. In the project this came
from, one validity check reported clean for weeks while it was keyed off a leftover variable and
could only ever hold one entry.

When you write a check, break the thing it checks and confirm the check fails. The positive
control in `tests/domain/test_validity.py` was verified that way.
