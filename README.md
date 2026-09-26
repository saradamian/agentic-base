# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](https://github.com/saradamian/agentic-base/blob/main/pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](https://github.com/saradamian/agentic-base/blob/main/CITATION.cff)

Records what an AI agent did, for the people who will ask about it later, and refuses a record
nobody could check.

## It refuses three things

**An outcome with no scorer.** `POST /runs` with `resolved: true` and no `label_source` returns
HTTP 422. "It worked" is worth nothing to the next reader unless the record says who decided:
the benchmark's own harness, a maintainer, the agent grading itself. Those are not the same
claim, and only the first two can be cited.

**A comparison that lost runs unevenly.** One agent resolves 85.7 % and another 52.6 %. The first
also timed out on six hard tasks, the second on one, and a timeout has no verdict. Count every
run and the gap is 60 % against 50 %. `validity` catches this and shows the per-arm accounting.
Clinical trials have published that accounting since 2001, as the CONSORT flow diagram. No
experiment tracker we found checks it.

**Personal data on the shared tier.** A run classified `personal` or `health` that names the
`community` isolation tier is rejected at the write path. It is the one combination no regime
permits.

## Who asks later

The person the agent worked for. An auditor. An incident responder. A regulator with
the AI Act in hand. Most agents keep a debug log for their developers, which answers none of
them.

Each record says who the run acted for, what class of data it touched and on which tier, whether
personal data was removed from the transcript and by what, who approved which action, and
whether the person was told they were dealing with an AI. Every create, label and approval joins
a hash chain per tenant — position-numbered, head-anchored, holding personal fields only as
digests — and `GET /runs/integrity` reports what it verified. A transcript can be redacted on the
way in, and a person erased on request or on a schedule, with the chain still verifying and the
verification reporting the erasure. A tenant takes its whole corpus away in one request, in the
shape the write path accepts.

Only two fields are required: the tenant and the code revision. A writer that does not know the
rest yet still writes, and the corpus can tell a run recorded before an answer existed from one
recorded after.

## What you use it for

| you want to | use | what it gives you |
|---|---|---|
| keep an account of what your agent did | the service, through `agentic_base.client` | records under audit, per tenant, behind bearer tokens |
| hand a run to someone else's tooling | `agentic_base.provenance` | W3C PROV, a Process Run Crate, an OpenLineage event, each through that standard's own library |
| know whether version B beats version A | `agentic_base.domain.validity` | a verdict with a 95% interval on it, the exclusion channels behind it — runs never attempted included — and whether the check could have flagged anything |
| see runs in a tracker you already have | `agentic-base-mlflow` | each run as an MLflow trace with a feedback assessment |
| ask about runs from a chat client | `agentic-base-mcp` | four read-only tools over the same database, only for the tenants `MCP_TENANTS` names |
| stop an agent fetching an internal URL | `agentic_base.security.netsec` | URL validation with DNS pinning |
| remove personal data before it is stored | `agentic_base.redaction` | patterns always, names from a model with a fallback, refusing to write when neither can answer |

Smaller pieces an agent on a shared platform tends to get wrong when it writes its own: a
pre-filter over generated code, a probe that asks a model for a completion instead of trusting a
status code, a retry policy that replaces a dead connection pool, a value returned from a batch
job over its stdout. [Boundaries](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/boundaries.md)
lists them all.

The library half runs on Python 3.10 with four dependencies and no database, because that is the
floor its first consumer runs on. The service is an extra.

## What it is not

Not an agent framework, a tracing backend, a metrics store, an experiment tracker, a workflow
engine or an inference server. Each exists and is better than one we would write.
[The reuse ledger](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/reuse-ledger.md)
gives a verdict per concern, adopt, bridge or build, and a test fails when the code does by hand
what the ledger says it adopted. It does not drive execution either: the orchestrator and the
model server are other systems.

It is built on the SURF Developer Platform golden path, and it is the contracts layer under a set
of capability blocks, one per SURF system, that live in their own packages. See
[blocks and layers](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/blocks.md).

## Installing

```bash
pip install surf-agentic-base                # the library half: four dependencies, Python 3.10+
pip install 'surf-agentic-base[provenance]'  # plus the three provenance-standard libraries
pip install 'surf-agentic-base[service]'     # the service: FastAPI, storage, tracing, MCP
pip install 'surf-agentic-base[mlflow]'      # plus the MLflow export
```

The import name is `agentic_base`. The distribution is named `surf-agentic-base` because
`agentic-base` on PyPI belongs to an unrelated project.

## Try it

Three runnable examples, each with its output committed beside it and checked by a test, so what
you see below is what you will get.

**An agent that works for people.** `examples/service_agent.py` records a merge-request review
agent's runs through the client: who each review was for, the data class and tier, how the person
was told it was an AI, a maintainer's approval, and three verdicts of different standing. Then it
reads back everything the agent did for one person, and checks the records are intact.

```bash
pip install 'surf-agentic-base[service]'
export API_TOKENS='{"example-token-0000001": {"tenants": ["example-team", "platform-team"], "label_sources": ["official_harness", "human"]}}'
REDACTION=patterns just run          # in one terminal
python examples/service_agent.py     # in another
```

```text
1. Three reviews, each recorded for the person who asked
   recorded 3 runs

2. The agent wanted to push to mr-103; a maintainer decided
   approval recorded

3. Verdicts on the reviews, and which of them mean anything
   mr-101  the developer's thumbs-up    user_feedback  diagnostic
   mr-102  another model's score        model_judge    diagnostic
   mr-103  the maintainer's decision    human          authoritative

4. Everything the agent did for alice, from the tenant's export
   mr-101: Automated review: Looks fine; one missing test for the retry path.
     told it was an AI: every review comment begins 'Automated review:'
     data class internal, tier virtualised
     approvals: none
     stored question: Review mr-101. Questions to <EMAIL_ADDRESS>.
   mr-103: Automated review: Suggest a fix: pin the base image by digest. Push it?
     told it was an AI: every review comment begins 'Automated review:'
     data class internal, tier virtualised
     approvals: approved by urn:example:maintainer-carol
     stored question: Review mr-103. Questions to <EMAIL_ADDRESS>.

5. Are the records as they were written?
   intact: 3 runs match 7 entries
```

**Without the service.** `examples/is_this_comparison_sound.py` uses the library half on a record
type of its own. Two configurations of an agent attempt twenty tasks; one looks far better only
because it times out on the hardest six, and a timeout has no verdict.

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

**With the service.** `examples/record_and_ask.py` records runs from a stand-in agent through the
client, including one that crashes, labels them, and asks the service whether the comparison is
sound, whether the records are intact, what was kept of a transcript, and for one run in W3C PROV.

```bash
pip install 'surf-agentic-base[service,provenance]'
export API_TOKENS='{"example-token-0000001": {"tenants": ["example-team", "platform-team"], "label_sources": ["official_harness", "human"]}}'
REDACTION=patterns just run        # in one terminal
python examples/record_and_ask.py  # in another
```

```text
1. Recording 12 runs to http://localhost:8080
   the run that crashed was kept: status=failed, failure_kind=RuntimeError

2. Labelling the finished runs with the benchmark's own harness
   a label that names no scorer is refused: HTTP 422

3. Is the comparison sound?
   inconclusive: too little data — timeout: 33.3% (with-planner) vs 0.0% (baseline), 95% interval -12.3 to +70.0 pp
   baseline: assessed 6; excluded 0 (none); analysed 6
   with-planner: assessed 6; excluded 2 (2 timeout); analysed 4

4. Are the records as they were written?
   intact: 12 runs match 22 entries

5. What was stored of the transcript
   (the crashed run has no transcript)
   Fix task-1. Mail the report to <EMAIL_ADDRESS>.
   redaction: agentic-base <version> patterns, no names or places

6. One run in W3C PROV, for a reader that is not this service
   sections: activity, agent, entity, prefix, used, wasAssociatedWith, wasAttributedTo, wasGeneratedBy
   the outcome: {"ab:authority": "authoritative", "ab:degraded": false, "ab:instrument": "harness-1.4", "ab:label_source": "official_harness", "ab:resolved": true}

7. Everything this tenant recorded, to take elsewhere
   manifest says 12 records; the file has 12
   the same request without the token: HTTP 401
```

`<version>` is the installed package version.

**From a chat client.** `agentic-base-mcp` serves the same database read-only over MCP, with four
tools: `list_runs`, `get_run`, `validity_report` and `corpus_stats`. Point it at the database the
service writes, in the `mcpServers` block of Claude Desktop or a project's `.mcp.json`. It opens
that database itself, so it runs where its user may already read the database and is never
published as a network service. `MCP_TENANTS` names the tenants it may serve: without it the
server refuses to start, and `*` serves every tenant deliberately, with a warning — the same rule
as `AUTH=none`:

```json
{
  "mcpServers": {
    "agentic-base": {
      "command": "agentic-base-mcp",
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/agentic-base.db",
        "MCP_TENANTS": "example-team"
      }
    }
  }
}
```

Then ask it, for example, whether the comparison for `example-team` is sound.

`get_run` returns a long transcript in pages, so no part of a run is out of reach:
`transcript.next_message` says where the next page starts, and a call with `from_message` set to
it returns that page. A page holds at most `AP_MCP_MAX_TRANSCRIPT_CHARS` characters of messages,
60,000 unless set, and `0` removes the limit. A caller can ask for smaller pages with `max_chars`.
A message longer than the limit is returned whole rather than cut, and the system prompt comes
whole on the first page. `list_runs` returns at most `AP_MCP_MAX_ROWS` rows, 200 unless set, and
says how many there were.

## Running locally

```bash
just run          # uvicorn with reload on :8080
just check        # tests with coverage, ruff, mypy
```

SQLite by default so it runs with no infrastructure. PostgreSQL, provided as a platform tenant
resource, in every deployed environment.

Every data route requires a bearer token. `API_TOKENS` maps each token to the tenants it may use,
`["*"]` for all of them, and comes from the platform's secret management. A token may instead map
to `{"tenants": [...], "label_sources": [...]}`; only the citable sources named there — the
benchmark's own harness or grader, or a person — may be asserted through it, and the plain list
shape grants none, so a writer token records diagnostic outcomes and cannot mint citable results.
With no tokens set the service refuses every data request and says what to set; `AUTH=none` turns
the check off for local development, and the service logs a warning when it starts that way.

```bash
AUTH=none just run
```

## Documentation

- [Blocks and layers](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/blocks.md): the design, what exists behind each block, the order to build
- [Decisions](https://github.com/saradamian/agentic-base/blob/main/docs/decisions.md): eleven choices that are cheap now and expensive to reverse
- [Reuse ledger](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/reuse-ledger.md): adopt, bridge, or build, with the reason
- [Logging, security, safety and compliance](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/cross-cutting.md): where each lives, the obligations, and what the vision should say
- [Observability](https://github.com/saradamian/agentic-base/blob/main/docs/OBSERVABILITY.md): what the service emits and where to point it
- [Compliance evidence](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/compliance.md): what the record produces for the AI Act, NIS2, the Cyber Resilience Act and the Data Act, and what is missing
- [Redaction](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/redaction.md): what removes personal data from a transcript, and what each mode catches and costs
- [Incident response](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/incident-response.md): the two reporting clocks, who is told, and what this repository hands you
- [Going live on SDP](https://github.com/saradamian/agentic-base/blob/main/docs/architecture/go-live-on-sdp.md): the deployment repository and what is left to settle
- [Archive](https://github.com/saradamian/agentic-base/blob/main/archive/README.md): superseded pages, kept for the record

## The standard

`docs/ENGINEERING.md` is why the rules are the rules: what each cost to learn, and the guard that
enforces it. `CONTRIBUTING.md` is the short form for someone about to open a pull request.

## Where development happens

Here. Changes land on `main` through pull requests that the gate has passed on both ends of the
supported Python range. SURF's own deployment of this service, the environment overlays and the
internal pipeline definition, is kept apart from this repository because it describes where the
software runs rather than what it does. The mechanism is general and is documented in
`docs/architecture/deployment-overlay.md`: a deployment repository is this one plus an additive
overlay, kept current by merging `main`, with `scripts/overlay.py` to compose, check and sync.

## Versioning and releases

Semantic versioning, with the version taken from the git tag. While the major version is `0`, a
minor bump may change the public interface. The import name changed once, from `app` to
`agentic_base` in `0.2.0`, because a top-level `app` collides with the first package any
consumer of a web template already has. Releases are signed `vX.Y.Z` tags; each is published to
PyPI by trusted publishing, with generated notes, build provenance and an SBOM attested on the
distribution files. See `CONTRIBUTING.md` for the release procedure.

## Citation

Cite the repository using `CITATION.cff`; GitHub renders it under *Cite this repository*.

## Licence

European Union Public Licence v. 1.2. See `LICENSE`.
