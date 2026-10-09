# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](https://github.com/saradamian/agentic-base/blob/main/CITATION.cff)

The record of what an AI agent did, kept so that the people who have to answer for it can read
it later. One run is one record. It says what the model received, who the run acted for, what
class of data it touched and on which tier, who approved which action, whether the person was told
they were dealing with an AI, and who scored the outcome. Agents write it. The person it worked
for, an auditor, an incident responder and the person comparing two versions read it.

This repository is that contract and the pieces around it: the record type with the rules a
writer must meet, a service that keeps records per tenant under audit, exports in the provenance
standards, and the small library a tool server needs. Two checks on claims about agents come out
of the record, and they also run on logs you already have.

## The contract

A run record carries these fields, in groups:

| group | fields |
|---|---|
| where it came from | `tenant`, `code_revision`, `component_versions`, `model`, `endpoint`, `precision`, `system_prompt`, `messages` |
| for whom, on what | `principal`, `classification`, `isolation_tier`, `disclosure`, `content_marking`, `redaction` |
| oversight | `approvals`, each saying who said yes to which action and when |
| the outcome | `status`, `resolved`, `label_source` (who scored it), `instrument`, `degraded` |
| what it cost | `prompt_tokens`, `completion_tokens`, `joules`, `num_steps`, `total_tool_calls`, `elapsed_ms` |
| for a comparison | `item`, `arm`, `arm_fingerprint`, `failure_kind` |

Only `tenant` and `code_revision` are required, so a writer that does not know the rest yet still
writes. The service refuses three things at the write path: an outcome with no scorer, personal or
health data on the shared tier, and a transcript that redaction could not process. Every create,
label and approval joins a per-tenant hash chain, verified on request. A person can be erased with
the chain still verifying.

The type is `agentic_base.domain.outcomes.RunRecordCreate`. The rules over it are functions on a
structural protocol, so a consumer with its own record type gets them without adopting the
storage. The library half runs on Python 3.10 with four dependencies and no database. The words
(principal, scorer, citable, exclusion channel) are defined in
[Concepts](https://github.com/saradamian/agentic-base/blob/main/docs/concepts.md).

## Record a run

```python
from agentic_base.client import RunRecorder
from agentic_base.domain.outcomes import DataClass, IsolationTier

recorder = RunRecorder("http://localhost:8080", tenant="example-team", code_revision="7c1e0d2", token=TOKEN)
with recorder.run(
    item="mr-103",
    arm="reviewer-2026.09",
    model="some-model",
    principal="urn:example:alice",
    classification=DataClass.INTERNAL,
    isolation_tier=IsolationTier.VIRTUALISED,
) as run:
    run.messages = [{"role": "user", "content": "Review mr-103."}, {"role": "assistant", "content": "..."}]
```

The record is written when the block exits, also on an exception. `examples/service_agent.py` is
the whole story for a review agent: three runs, how each person was told it was an AI, a
maintainer's approval, and three verdicts of different standing.
[Running the service](https://github.com/saradamian/agentic-base/blob/main/docs/service.md) has
the install, the tokens, and what each example prints.

## Read it back

- `GET /runs/integrity` verifies the tenant's chain and names a changed, cut or missing entry.
- `GET /runs/{run_id}/provenance?format=...` returns the run as W3C PROV, an OpenLineage event
  or a Process Run Crate, so someone else's tooling reads it without learning ours.
- `agentic-base-mlflow` exports a tenant into MLflow. `agentic-base-mcp` serves the database
  read-only to a chat client.
- The spans the service emits carry the OpenTelemetry GenAI and OpenInference vocabulary, so
  Phoenix, Langfuse and Jaeger label them without translation
  ([Observability](https://github.com/saradamian/agentic-base/blob/main/docs/OBSERVABILITY.md)).

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
- `observer_from_environment` returns a recorder that appends one JSON line per call, failed
  calls included. By default the lines go to one file a month in
  `~/.local/state/agentic-base/calls` (under `$XDG_STATE_HOME` when that is set), readable by
  you only, for six months. `AP_CALL_LOG` names another file, and `AP_CALL_LOG=off` records nothing. A host with
  its own journal implements `CallObserver` instead.
- `ObservingMiddleware` puts that observer in front of every tool call of a server built on the
  MCP SDK: `MCPServer(name, middleware=[ObservingMiddleware(observer_from_environment(server=name))])`.
  It imports nothing from the SDK, so it adds no dependency to the library half. Each line then
  also says which client and request the call came from, its trace and span ids, the caller's
  `_meta` keys and, for a failed call, the error the client got. An agent that sends its run id
  as `_meta["agentic_base.run_id"]` gets its calls joined to its run record.

What is deliberately not here: the server loop itself. The MCP SDK has it, and a server of a few
tools is about a hundred lines on the SDK's low-level `Server`.

### See what agents did with it

`agentic-base calls` reads the call log back. This is a short session of an MCP client with the
EasyBuild server, which is built on this library:

```console
$ agentic-base calls
7 calls to 1 server, at 2026-10-09 03:13 UTC, in ~/.local/state/agentic-base/calls

server     tool                 calls  failed  median ms  p95 ms
easybuild  compute_checksum         2       1         56     106
easybuild  pypi_info                2       1        109     174
easybuild  github_release_info      1       0        226     226
easybuild  list_toolchains          1       0          0       0
easybuild  search_easyconfigs       1       0         58      58

clients: mcp 0.1.0 (7)

agentic-base calls --failures shows each failed call with its arguments.

$ agentic-base calls --failures
2026-10-09 03:13  easybuild  pypi_info  {"package": "tqdm-but-misspelt-xyz"}
  PyPI has no package 'tqdm-but-misspelt-xyz'
2026-10-09 03:13  easybuild  compute_checksum  {"url": "http://169.254.169.254/latest/meta-data"}
  URL rejected: disallowed address: 169.254.169.254
```

The second failure is the checked fetch refusing a cloud metadata address. Each failed call
shows what the agent asked for and the error it got back. `--since 7d` and `--server` narrow the
log down, and `--json` gives the same summary to a script.

## Check a comparison

Because the record names the scorer and the reason a run has no verdict, two checks follow from
it: did the comparison lose runs unevenly, and who scored each outcome. They also read logs you
already have, with no server, database or token:

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

The exit code gates a CI job: **0** sound, **1** not sound, **2** when the input cannot answer
either way. [Check a comparison](https://github.com/saradamian/agentic-base/blob/main/docs/checks.md)
has the input formats, the CI snippet, and the same check from Python over a record type of your
own.

## What you use it for

| you want to | use |
|---|---|
| keep an account of what your agent did, for whom, with whose approval | the service, through `agentic_base.client` |
| hand a run to someone else's tooling | `agentic_base.provenance`: W3C PROV, a Process Run Crate, an OpenLineage event |
| see runs in a tracker you already have | `agentic-base-mlflow` |
| ask about runs from a chat client | `agentic-base-mcp`, read-only |
| remove personal data before it is stored | `agentic_base.redaction` |
| declare a tool a model can call | `agentic_base.tools` |
| pre-check a URL an agent wants to fetch, or stream a file from it | `agentic_base.security.netsec` |
| record the calls a served tool receives | `agentic_base.recording` |
| see what agents did with your tool server | `agentic-base calls` |
| know which outcomes may be cited | `agentic_base.domain.outcomes` |
| check whether version B really beats version A | `agentic-base check`, or `agentic_base.domain.validity` |

`netsec` validates a URL and pins the address it resolved to. It bounds accidental damage; it is
not a network boundary, and address forms or paths it does not know about get through. Where an
agent is untrusted, enforce egress in the network as well, with an egress proxy or a network
policy that allows only the destinations you intend.

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
- [Check a comparison](https://github.com/saradamian/agentic-base/blob/main/docs/checks.md): the two checks, over the record or over logs you already have
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
