# Start here

Three pages, and then the code. This is not a specification and there is no larger document
behind it that you are supposed to read first.

## The service, in plain terms

A system of record for agent runs, and a referee for claims made from that record.

You post a run and it stores what the model actually received, the environment it ran in, and a
fingerprint of the configuration. You attach an outcome later and it will not let you do that
without naming who decided. It will tell you whether a comparison between two configurations is
sound. It hash-chains records so an edit after the fact is detectable, and it exposes all of that
read-only over MCP so someone in a chat client can ask.

That is the whole of it today. It does not run agents, serve models, schedule anything, or train.

## Why it is shaped this way

Most experiment tooling stores what a run produced. Very little of it stores who decided the run
was correct, or whether the thing that decided was working at the time. None of it tells you your
comparison is invalid. That gap is the reason this exists, and it only closes if the refusals are
in the write path from the first day, because provenance cannot be retrofitted onto runs that did
not record it.

## Read these four, in this order

1. `docs/decisions.md`. Seven decisions, each one cheap now and expensive later. D5 explains why
   two arguments have no default and why that is not an oversight.
2. `docs/architecture/reuse-ledger.md`. What is adopted and from where. Most of what a platform
   needs already exists inside SURF, and the list is longer than people expect.
3. `docs/architecture/operational-traps.md`. Failures that are invisible in code review. Several
   apply to code that is not in this repository, because the shape recurs.
4. `tests/lessons/`. One test file, no framework, forty lines. It demonstrates how a retrieval bug
   makes a measurement return a clean zero that reads exactly like a finding.

## What is dormant, and should be left alone for now

These are in the repository because they were cheap to write while the context was fresh, and
they answer questions nobody has yet asked of a system with no users. Do not build on them, and
do not let their presence suggest what this project is about.

- The hash chain over audit fields, and the AI Act and NIS2 evidence mapping. Real obligations,
  no users yet.
- The energy column. It is a real axis when you are billed for an allocation, and it will be zero
  here for a long time. A column that is always zero teaches people to ignore columns.
- The Snellius and LUMI profiles. They are worked examples of what a cluster profile has to carry,
  not a statement that HPC is the destination.

## The first useful thing to do

Instrument something you already have. `src/app/client.py` is about ten lines at the call site.
Record twenty runs of anything, label half of them, and ask for the validity report. You will
find out quickly whether the required fields are in the right places, and that is worth more than
any opinion in this document.

## The habit that matters most

A guard that cannot fail is worse than no guard, because it gets cited. In the project this came
from, one validity check reported clean for weeks while it was keyed off a leftover variable and
could only ever hold a single entry.

So when you write a check, break the thing it checks and confirm the check fails. The positive
control in `tests/domain/test_validity.py` was verified that way, not assumed.
