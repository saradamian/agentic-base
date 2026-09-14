# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](CITATION.cff)

The agentic base layer for SURF: **a system of record for what agents do, a referee for claims
made from that record, the security primitives an agent needs on a shared platform, and the
engineering standard that keeps all of it honest**. It is the contracts layer under a set of capability blocks, one per SURF system, that
live in their own packages; see `docs/architecture/blocks.md`.

It is built on the SURF Developer Platform golden path and adopts the common stack wherever the
common stack has an answer. It contains only the parts we could not find anywhere else.

## The problem it addresses

An agent that works for people on a shared platform acts for someone, touches data of some class,
sometimes does things a person should approve, and talks to people who have a right to know it is
an AI. Afterwards someone asks what it did: the person it worked for, an auditor, an incident
responder, a regulator. Most agents keep a log for their developers and nothing that answers
those questions. This service records each run with that account, and keeps it intact.

When a team changes its agent, a new model, a new prompt, a benchmark arm, it also wants to know
whether the new one is better, and that comparison is easy to get wrong. The service is a referee
for that as well. It does not drive execution: the job orchestrator and the model server are
other systems, and the two HPC modules here are a result channel and cluster facts, nothing more.

## Adopted, not written here

It does not ship an agent framework, a tracing backend, a metrics store, a dashboard, an experiment
tracker, a workflow engine, or an inference server. Every one of those exists and is better than
anything we would write. See [the reuse ledger](docs/architecture/reuse-ledger.md) for what is
adopted and from where.

## The record, for any agent

`agentic_base.domain.run_record` holds one row per run: the transcript the model actually
received, the environment it ran in, and who decided its outcome. Every record also says who the
run acted for, what class of data it touched and on which isolation tier, whether personal data
was redacted before the transcript was written and by what, who approved which action, whether
the person was told they were dealing with an AI, and how generated output was marked. Only the
tenant and the code revision are required; the rest have defaults, so a writer that does not
know yet still writes, and the corpus can tell a run recorded before the answer existed from one
recorded after. `docs/architecture/cross-cutting.md` says which obligation each field serves.

Every write goes into a hash-chained audit log that `GET /runs/integrity` verifies. A transcript
can be redacted on the way in and erased later under a retention policy without breaking that
chain, and a tenant can export everything it recorded in one request.

An outcome cannot be recorded without naming who decided it, and only some deciders count. A
benchmark's own harness or a person whose decision is the reference is citable; the agent's own
claim, a quick in-tree check, a user's thumbs-up or another model's score is kept and marked as
diagnostic. Experiment trackers that record who decided type it by modality, human, model or
code, which cannot tell a user's thumbs-up from a reviewer's decision, and none refuses an
outcome that names no one.

Nothing is exported in a private format. `agentic_base.provenance` turns one record into W3C
PROV, an OpenLineage run event and a Process Run Crate, each through that standard's own library,
with the scorer and its authority carried as a declared extension whose schema is in
`docs/schemas/`. The same record exports into MLflow as a trace with a feedback assessment;
`agentic-base-mlflow --tenant <name>` sends a tenant's runs from the service's database.

## The referee, when you compare

`agentic_base.domain.validity` adjudicates whether a contrast across arms is sound: benchmark
arms, or two versions of a service agent. It detects exclusion channels whose rate differs by arm,
which do not cancel in a contrast, and reports the per-arm accounting behind the verdict.
`item` names the unit of work two runs must share to be compared, `arm` names what is being
compared; a record that compares nothing leaves both empty.

The referee is not a new mechanism. Clinical trials have shipped exactly this artifact for two
decades: the **CONSORT flow diagram**, a per-arm accounting of everyone who left the denominator
and why, mandatory for publication since 2001, with an extension for AI interventions since 2020.
The defect it exposes has a name in the missing-data literature, missingness that is **MNAR with
respect to the treatment arm**. What is missing is not the idea. No experiment tracker implements
the check, and we found no reporting standard in agent evaluation that requires the accounting,
so `validity` implements the check and `flow_by_arm` produces the accounting in the standard's
vocabulary: assessed, excluded with reasons, analysed.

## The rest of the library

Small things an agent on a shared platform gets wrong when it writes its own: the outbound URL
check with DNS pinning, the structural pre-filter over generated code, a completion probe that
asks a model for an answer instead of trusting a status code, a retry policy that recycles a
dead transport, cluster facts without credentials, a value back from a batch job, the tool
contract, the span vocabulary from the standard packages, and the recording seam a served call
passes through. Two more that exist because a regime asks for them and the record is where they
land: redaction of a transcript before it is written, patterns always and names from a model with
a fallback, failing closed rather than claiming more than ran; and a retention policy that
refuses to keep less than the law requires, with an erasure the hash chain survives.
`docs/architecture/boundaries.md` lists them; `docs/architecture/reuse-ledger.md` says for each whether it is adopted, bridged or built, and a test holds the code to that ledger.

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
   not sound: timeout: 30.0% (with-planner) vs 5.0% (baseline)
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
REDACTION=patterns just run        # in one terminal
python examples/record_and_ask.py  # in another
```

```text
1. Recording 12 runs to http://localhost:8080
   the run that crashed was kept: status=failed, failure_kind=RuntimeError

2. Labelling the finished runs with the benchmark's own harness
   a label that names no scorer is refused: HTTP 422

3. Is the comparison sound?
   not sound: timeout: 33.3% (with-planner) vs 0.0% (baseline)
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
```

`<version>` is the installed package version.

**From a chat client.** `agentic-base-mcp` serves the same database read-only over MCP, with four
tools: `list_runs`, `get_run`, `validity_report` and `corpus_stats`. Point it at the database the
service writes, in the `mcpServers` block of Claude Desktop or a project's `.mcp.json`:

```json
{
  "mcpServers": {
    "agentic-base": {
      "command": "agentic-base-mcp",
      "env": { "DATABASE_URL": "sqlite:////absolute/path/to/agentic-base.db" }
    }
  }
}
```

Then ask it, for example, whether the comparison for `example-team` is sound.

## Running locally

```bash
just run          # uvicorn with reload on :8080
just check        # tests with coverage, ruff, mypy
```

SQLite by default so it runs with no infrastructure. PostgreSQL, provided as a platform tenant
resource, in every deployed environment.

## Documentation

- [Blocks and layers](docs/architecture/blocks.md): the design, what exists behind each block, the order to build
- [Decisions](docs/decisions.md): eleven choices that are cheap now and expensive to reverse
- [Reuse ledger](docs/architecture/reuse-ledger.md): adopt, bridge, or build, with the reason
- [Logging, security, safety and compliance](docs/architecture/cross-cutting.md): where each lives, the obligations, and what the vision should say
- [Observability](docs/OBSERVABILITY.md): what the service emits and where to point it
- [What came from agentic-env](docs/architecture/from-agentic-env.md): what was extracted, what was left, what the first consumer found
- [Compliance evidence](docs/architecture/compliance.md): what the record produces for the AI Act, NIS2, the Cyber Resilience Act and the Data Act, and what is missing
- [Redaction](docs/architecture/redaction.md): what removes personal data from a transcript, and what each mode catches and costs
- [Incident response](docs/architecture/incident-response.md): the two reporting clocks, who is told, and what this repository hands you
- [Going live on SDP](docs/architecture/go-live-on-sdp.md): the deployment repository and what is left to settle

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
