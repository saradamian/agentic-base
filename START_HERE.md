# Start here

Three pages, then the code.

1. `README.md`: the record and what it carries, the service that keeps it, the library a tool
   server needs, and the two checks that come out of the record.
2. `docs/concepts.md`: the fifteen terms, each pointing at the field or function it names.
3. `docs/service.md`: running the service, with two worked examples.

Then read `src/agentic_base/domain/outcomes.py`. It holds the record type and the rules over it.
Everything else in the package stores, moves, exports or checks that record;
`src/agentic_base/domain/validity.py` is the check that reads it to say whether a comparison is
sound.

## Who uses it

agentic-env, the agent runtime this came out of, imports the outcome vocabulary, the version
declarations, the job-result protocol for batch jobs, the span vocabulary and the provenance
emitters from here, and records the installed version of this package beside every run. The
EasyBuild MCP server in SURF's agentic-ai-dev group builds its tools on the tool decorator, the
checked fetch and the call recorder.

## The first useful thing to do

Record one run. Start the service and run `examples/service_agent.py`, as `docs/service.md` shows;
the record it writes names the person the run was for, the approval and who scored it. Then read
the run back through `GET /runs/integrity` and the provenance export.

Or point `agentic-base check` at results you already have. If your logs are JSONL or a CSV table
(a spreadsheet, or an MLflow `search_runs` export), name the fields with `--arm`, `--item`,
`--verdict` and `--channel`; if they are Inspect AI logs, pass the `.eval` file. You will find out in a minute whether your comparison lost runs unevenly, and whether your
logs record who scored each outcome at all.

## The habit that matters most

A guard that cannot fail is worse than no guard, because it gets cited. In the project this came
from, one validity check reported clean for weeks while it was keyed off a leftover variable and
could only ever hold one entry. That is why `agentic-base check` exits 2, not 0, when it could not
have flagged anything.

When you write a check, break the thing it checks and confirm the check fails. The positive
control in `tests/domain/test_validity.py` was verified that way.
