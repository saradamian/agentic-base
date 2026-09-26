# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](https://github.com/saradamian/agentic-base/blob/main/CITATION.cff)

Two checks for claims about AI agents, and a service that records agent runs so the checks can be
made later.

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
agentic-base check examples/results.jsonl --arm config
```

```text
baseline: assessed 20; excluded 1 (1 timeout); analysed 19
with-planner: assessed 20; excluded 6 (6 timeout); analysed 14
not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline), 95% interval +0.8 to +47.3 pp
outcomes: 27 name a citable scorer, 4 diagnostic, 2 name none
```

`agentic-base check` reads JSONL (one JSON object per run; `--arm`, `--item`, `--verdict`,
`--channel` and `--scorer` name the fields) or an Inspect AI `.eval`/`.json` log, where `--arm` is
`model`, `task` or a metadata key. A row with no verdict is counted as an exclusion, never
silently analysed. The exit code gates a CI job: **0** sound, **1** not sound, **2** when the input
cannot answer either way (too little data, one arm, no exclusion anywhere, or an unreadable file).
`--json` prints the full report.

No logs at hand? `python -m agentic_base.demo` builds the scenario above in memory and prints the
flattering number beside the checked verdict.

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
| pre-check a URL an agent wants to fetch | `agentic_base.security.netsec` |

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
