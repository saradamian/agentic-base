# Start here

Three pages, then the code.

1. `README.md`: the two checks, and `agentic-base check` over logs you already have.
2. `docs/concepts.md`: the fifteen terms, each pointing at the field or function it names.
3. `docs/service.md`: the service, for when you want the record and not only the check.

Then read `src/agentic_base/domain/validity.py` and `src/agentic_base/domain/outcomes.py`. They
are the whole of the two checks; everything else in the package is storage, transport or export
around them.

## Who uses it

agentic-env, the experiment harness this came out of, imports the outcome vocabulary, the version
declarations, the job-result protocol for batch jobs, the span vocabulary and the provenance
emitters from here, and records the installed version of this package beside every run.

## The first useful thing to do

Point `agentic-base check` at results you already have. If your logs are JSONL, name the fields
with `--arm`, `--item`, `--verdict` and `--channel`; if they are Inspect AI logs, pass the `.eval`
file. You will find out in a minute whether your comparison lost runs unevenly, and whether your
logs record who scored each outcome at all.

## The habit that matters most

A guard that cannot fail is worse than no guard, because it gets cited. In the project this came
from, one validity check reported clean for weeks while it was keyed off a leftover variable and
could only ever hold one entry. That is why `agentic-base check` exits 2, not 0, when it could not
have flagged anything.

When you write a check, break the thing it checks and confirm the check fails. The positive
control in `tests/domain/test_validity.py` was verified that way.
