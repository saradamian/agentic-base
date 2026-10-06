# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](https://github.com/saradamian/agentic-base/blob/main/CITATION.cff)

Three things for people who build and evaluate AI agents: two checks for claims about them, a
service that records agent runs so the checks can be made later, and the small library a tool
server needs.

- **Did the comparison lose runs unevenly?** One agent resolves 85.7% and another 52.6%. The first
  also timed out on six hard tasks, the second on one, and a timeout has no verdict. Count every
  run and the gap is 60% against 50%. The check finds this, with a 95% interval, and shows the
  per-arm accounting clinical trials publish as the CONSORT flow diagram.
- **Who scored each outcome?** The benchmark's own harness and a person can be cited. The agent
  grading itself, another model's score and a user's thumbs-up are worth keeping and are not
  results. The check counts which is which.

## Try it on logs you already have

No server, database or token:

```bash
pip install surf-agentic-base
python -m agentic_base.demo --jsonl > results.jsonl   # forty example runs; or use a log of your own
agentic-base check results.jsonl --arm config
```

```text
baseline: assessed 20; excluded 1 (1 timeout); analysed 19
with-planner: assessed 20; excluded 6 (6 timeout); analysed 14
not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline), 95% interval +0.8 to +47.3 pp
outcomes: 27 name a citable scorer, 4 diagnostic, 2 name none
```

`agentic-base check` reads JSONL (one JSON object per run; `--arm`, `--item`, `--verdict`,
`--channel` and `--scorer` name the fields), CSV with a header row (the same flags name the
columns), or an Inspect AI `.eval`/`.json` log, where `--arm` is `model`, `task` or a metadata key.
Runs kept in MLflow read through its own export: save `mlflow.search_runs(...).to_csv("runs.csv")`
and pass `--arm params.config --item params.task --verdict metrics.resolved`. A row with no
verdict is counted as an exclusion, never silently analysed. The exit code gates a CI job: **0**
sound, **1** not sound, **2** when the input cannot answer either way (too little data, one arm, no
exclusion anywhere, or an unreadable file). `--json` prints the full report.

`python -m agentic_base.demo` prints the flattering number for the same forty runs beside the
checked verdict. In a checkout they are `examples/results.jsonl`.

In CI, after the job that writes the results (GitLab shown; in GitHub Actions the same two
commands go in `run:` steps):

```yaml
comparison-is-sound:
  image: python:3.12
  script:
    - pip install surf-agentic-base
    - agentic-base check results.jsonl --arm config
  allow_failure:
    exit_codes: [2]   # too little data yet: say so, do not block
```

Exit 1 fails the job: the comparison lost runs unevenly, and a number reported from it would
mislead. Drop the `allow_failure` once there is enough data for 2 to mean a broken input.

## Use it from Python

`examples/is_this_comparison_sound.py` runs the same check over a record type of its own, through
`agentic_base.domain.validity` and `agentic_base.domain.outcomes`:

```bash
pip install surf-agentic-base
python examples/is_this_comparison_sound.py
```

```text
1. The number people report: resolved, over runs that finished
   baseline      10/19 = 52.6%
   with-planner  12/14 = 85.7%

2. What the validity check says
   not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline), 95% interval +0.8 to +47.3 pp
   examined 40 runs, 2 arms, 1 exclusion channel(s); could have flagged: True

3. The per-arm flow the verdict rests on
   baseline: assessed 20; excluded 1 (1 timeout); analysed 19
   with-planner: assessed 20; excluded 6 (6 timeout); analysed 14

4. Two honest numbers instead of one flattering one
   every run, a timeout counted as unresolved:
   baseline      10/20 = 50.0%
   with-planner  12/20 = 60.0%
   only the 14 tasks both arms finished:
   baseline      10/14 = 71.4%
   with-planner  12/14 = 85.7%

5. Which verdicts may be cited
   the benchmark's own harness        citable: True
   a quick in-tree check              citable: False
   the harness, but it failed open    citable: False
   the agent grading itself           citable: False
```

The library half runs on Python 3.10 with four dependencies and no database. The words it uses
(arm, exclusion channel, scorer, citable) are defined in
[Concepts](https://github.com/saradamian/agentic-base/blob/main/docs/concepts.md).

## Record runs as they happen

The service keeps every run an agent makes, per tenant, under audit: what the model received, who
the run acted for, what class of data it touched, who approved which action, whether the person
was told it was an AI, and who scored the outcome. It refuses an outcome with no scorer, personal
data on the shared tier, and a transcript it could not redact. Every write joins a hash chain
that is verified on request.
[Running the service](https://github.com/saradamian/agentic-base/blob/main/docs/service.md) shows two worked examples, the tokens, and the
read-only MCP server.

## What you use it for

| you want to | use |
|---|---|
| check whether version B really beats version A | `agentic-base check`, or `agentic_base.domain.validity` |
| know which outcomes may be cited | `agentic_base.domain.outcomes` |
| keep an account of what your agent did | the service, through `agentic_base.client` |
| hand a run to someone else's tooling | `agentic_base.provenance`: W3C PROV, a Process Run Crate, an OpenLineage event |
| see runs in a tracker you already have | `agentic-base-mlflow` |
| ask about runs from a chat client | `agentic-base-mcp`, read-only |
| remove personal data before it is stored | `agentic_base.redaction` |
| pre-check a URL an agent wants to fetch, or stream a file from it | `agentic_base.security.netsec` |
| declare a tool a model can call | `agentic_base.tools` |
| record the calls a served tool receives | `agentic_base.recording` |

`netsec` validates a URL and pins the address it resolved to. It bounds accidental damage; it is
not a network boundary, and address forms or paths it does not know about get through. Where an
agent is untrusted, enforce egress in the network as well, with an egress proxy or a network
policy that allows only the destinations you intend.

## Build a tool server on it

A server that gives an agent tools needs four things this library has: a way to declare a tool,
a result type, a fetch that refuses internal addresses on every hop, and a record of each call.
They are in the library half, which installs on Python 3.10 with four dependencies and no
database.

```python
import hashlib

import httpx

from agentic_base.recording import observer_from_environment
from agentic_base.security.netsec import URLSafetyError, open_checked
from agentic_base.tools.decorator import tool
from agentic_base.tools.types import ToolResult


@tool(description="The sha256 of the file at a URL.")
def checksum(url: str) -> ToolResult:
    try:
        with httpx.Client(follow_redirects=False) as client, open_checked(url, client=client) as response:
            digest = hashlib.sha256(response.read()).hexdigest()
    except URLSafetyError as exc:
        return ToolResult.fail(f"URL rejected: {exc}")
    return ToolResult.ok(digest)


observer = observer_from_environment(server="example")
observer.record("checksum", {"url": "https://example.org/x"}, "...", True, 12.0)
```

- `tool` turns the function into a `Tool` with a name, a description and typed parameters; the
  MCP SDK and an in-process registry both read that one object.
- `open_checked` validates the URL and every redirect target, connects to the address it
  validated, and yields the response before the body is read. `safe_fetch_text` does the same for
  a text.
- `observer_from_environment` returns a recorder that appends one JSON line per call to the file
  named by `CALL_LOG_VARIABLE`, failed calls included, and a no-op when that variable is not set.
  A host with its own journal implements `CallObserver` instead.

What is deliberately not here: the server loop itself. The MCP SDK has it, and a server of a few
tools is about a hundred lines on the SDK's low-level `Server`.

## What it is not

Not an agent framework, a tracing backend, a metrics store, an experiment tracker, a workflow
engine or an inference server. Each exists and is better than one we would write.
[The reuse ledger](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/reuse-ledger.md) gives a verdict per concern (adopt,
bridge or build), and a test fails when the code does by hand what the ledger says it adopted.

## Installing

```bash
pip install surf-agentic-base                # the library half: four dependencies, Python 3.10+
pip install 'surf-agentic-base[provenance]'  # plus the three provenance-standard libraries
pip install 'surf-agentic-base[service]'     # the service: FastAPI, storage, tracing, MCP
pip install 'surf-agentic-base[mlflow]'      # plus the MLflow export
```

The import name is `agentic_base`. The distribution is named `surf-agentic-base` because
`agentic-base` on PyPI belongs to an unrelated project.

## Documentation

- [Concepts](https://github.com/saradamian/agentic-base/blob/main/docs/concepts.md): the fifteen terms, each pointing at its code
- [Running the service](https://github.com/saradamian/agentic-base/blob/main/docs/service.md): worked examples, tokens, MCP, export
- [Decisions](https://github.com/saradamian/agentic-base/blob/main/docs/decisions.md): the choices that are cheap now and expensive to reverse
- [Compliance evidence](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/compliance.md): what the record produces for the AI Act, NIS2, the Cyber Resilience Act and the Data Act, and what is missing
- [Redaction](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/redaction.md) and [incident response](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/incident-response.md): for whoever operates the service
- [Reuse ledger](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/reuse-ledger.md): adopt, bridge or build, with the reason
- [Archive](https://github.com/saradamian/agentic-base/blob/main/archive/README.md): the design vision and other superseded pages, kept for the record

## Contributing and releases

`CONTRIBUTING.md` is the short form for someone about to open a pull request, and
`docs/ENGINEERING.md` is why the rules are the rules. Changes land on `main` through pull requests
that the gate has passed on both ends of the supported Python range. SURF's own deployment is
kept in a separate repository built from this one plus an overlay
(`docs/architecture/deployment-overlay.md`).

Semantic versioning, with the version taken from the git tag; while the major version is `0`, a
minor bump may change the public interface. Releases are signed `vX.Y.Z` tags, published to PyPI
by trusted publishing with build provenance and an SBOM attested on the distribution files.

Cite the repository using `CITATION.cff`. Licensed under the European Union Public Licence v. 1.2
(`LICENSE`).
