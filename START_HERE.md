# Start here

A few pages, then the code. There is no larger specification behind this.

## What the service does

It is a system of record for agent runs, and a referee for claims made from that record.

You post a run. The service stores what the model received, the environment it ran in, and a
fingerprint of the configuration. You attach an outcome later, and the service refuses it unless
you name who decided. It tells you whether a comparison between two configurations is sound. It
appends every write to a hash-chained audit log and verifies it on request, so a later edit is
detectable. Each record says who the run acted for, what class of data it touched and on which
isolation tier, whether the transcript was redacted and by what, whether the person was told they
were dealing with an AI, and who approved which action.

Three things it does on the way. When redaction is configured it removes personal data and
credentials from the transcript before writing it, and refuses the write rather than store a
transcript it could not redact. It knows which transcripts are older than a tenant's retention
policy, and how to erase one without breaking the chain. And a tenant can take its whole corpus
away in one request.

It serves a run in W3C PROV, OpenLineage or a Process Run Crate, exports it to MLflow, and
exposes the corpus read-only over MCP so someone in a chat client can ask.

That is all of it. It does not run agents, serve models, schedule jobs or train.

## What the library gives a consumer

Anything that imports `agentic_base` gets the rules without the storage: the outcome vocabulary
and the citability rules over a structural protocol, the validity check, the epoch declarations,
the retention policy and its erasure, the redaction seam with its pattern layer and its detectors,
the job-result protocol for batch jobs, the outbound URL check, the code pre-filter, the tool
contract, the recording seam, the span vocabulary, and the provenance emitters. It installs on
Python 3.10 with four dependencies. The service is an optional extra, and so is every model a
detector might use.

## Who it is for

agentic-env runs the experiments. It imports the job-result protocol, the span vocabulary, the
provenance emitters and the MCP transport from here, records the installed version of this
layer beside every run, and refuses to pool runs across an undeclared version. Each import
deleted a copy there.

Willma serves models. Anything here about inference points at Willma.

AI4Science submits and orchestrates jobs on Slurm. It runs agent jobs through a template script
on a shared filesystem. Replacing that seam with an interface is the hpc block's first job.

The AI Factory is buying a machine whose functional architecture has three verbs, train,
fine-tune and infer, with no box for an agent run and no plane for observing or evaluating one.
`docs/architecture/blocks.md` maps its tasks onto the blocks.

## Why it is shaped this way

Most experiment tooling stores what a run produced. Almost none of it stores who decided the run
was correct, or whether the thing that decided was working at the time. None of it tells you a
comparison is invalid. That gap is why this exists, and it closes only if the refusals are in the
write path from the first day. Provenance cannot be added to runs that did not record it.

## Where this sits

`docs/architecture/blocks.md` is the design: this repository is the contracts layer under twelve
capability blocks, one per SURF system, each in its own package with the system's owner, and
the capabilities that cut across every block: identity and delegated credentials, accounting,
triggers, oversight, classification, a ledger, redaction, and transparency. No block lives here.
`docs/architecture/cross-cutting.md` says where logging, security, safety and compliance live,
what the regimes ask of an agent platform, and which field on the record each gap became.

## Read these, in this order

1. `docs/decisions.md`. Eleven decisions, each cheap now and expensive later. D5 says why two
   arguments have no default. D10 says why no block is in this repository. D11 says why a gap
   with no solution still gets a field.
2. `docs/architecture/reuse-ledger.md`. What is adopted and from where. Most of what a platform
   needs already exists inside SURF, and a test holds the code to the ledger.
3. `docs/architecture/operational-traps.md`. Failures that are invisible in code review. Several
   apply to code that is not in this repository.
4. `tests/lessons/`. One test file, no framework. It shows how a retrieval bug makes a
   measurement return a clean zero that reads like a finding.

## What is dormant

These are here because they were cheap to write while the context was fresh. They answer
questions nobody has asked yet. Do not build on them.

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
