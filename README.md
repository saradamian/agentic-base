# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](CITATION.cff)

The agentic base layer for SURF: **the record and referee for agent runs, the security
primitives an agent needs on a shared platform, and the engineering standard that keeps both
honest**. It is the contracts layer under a set of capability blocks, one per SURF system, that
live in their own packages; see `docs/architecture/blocks.md`.

It is built on the SURF Developer Platform golden path and adopts the common stack wherever the
common stack has an answer. It contains only the parts we could not find anywhere else.

## The problem it addresses

Agent runs are a fourth execution pattern beside training, fine-tuning and inference: a long-lived
loop that consumes inference and executes code. They are expensive, hard to reproduce, and easy to
report wrongly. This service records what actually ran with enough provenance to replay it and to
audit it, and adjudicates whether a comparison between two configurations is sound enough to
publish. It does not drive execution: the job orchestrator and the model server are other
systems, and the two HPC modules here are a result channel and cluster facts, nothing more.

## Adopted, not written here

It does not ship an agent framework, a tracing backend, a metrics store, a dashboard, an experiment
tracker, a workflow engine, or an inference server. Every one of those exists and is better than
anything we would write. See [the reuse ledger](docs/architecture/reuse-ledger.md) for what is
adopted and from where.

## The record and the referee

| module | what it does | why nothing off the shelf does it |
|---|---|---|
| `agentic_base.domain.run_record` | one row per run: the transcript the model actually received, the provenance of its environment, and the provenance of its outcome label | experiment trackers record what a run produced. The ones that record who decided type it by modality, human, model or code, which cannot tell a convenience checker from an authoritative harness, and none refuses an outcome that names no scorer |
| `agentic_base.domain.validity` | adjudicates whether a contrast across arms is sound, by detecting exclusion channels whose rate differs by arm, and reports the per-arm accounting behind the verdict | trackers store, version and visualise runs. None of them tell you your comparison is invalid, and we found no reporting standard in agent evaluation that asks for the accounting that would show it |

Every record also says who the run acted for, what class of data it touched and on which
isolation tier, whether personal data was redacted before the transcript was written and by
what, who approved which action, whether the person was told they were dealing with an AI, and
how generated output was marked. Those fields have defaults, so a writer that does not know
yet still writes, and the corpus can tell a run recorded before the answer existed from one
recorded after. `docs/architecture/cross-cutting.md` says which obligation each one serves.

Neither is exported in a private format. `agentic_base.provenance` turns one record into W3C
PROV, an OpenLineage run event and a Process Run Crate, each through that standard's own library,
with the scorer and its authority carried as a declared extension whose schema is in
`docs/schemas/`. The same record exports into MLflow as a trace with a feedback assessment.

The referee is not a new mechanism. Clinical trials
have shipped exactly this artifact for two decades: the **CONSORT flow diagram**, a per-arm
accounting of everyone who left the denominator and why, mandatory for publication since 2001,
with an extension for AI interventions since 2020. The defect it exposes has a name in the
missing-data literature, missingness that is **MNAR with respect to the treatment arm**. What is
missing is not the idea. No experiment tracker implements the check, and we found no reporting
standard in agent evaluation that requires the accounting, so `validity` implements the check and
`flow_by_arm` produces the accounting in the standard's vocabulary: assessed, excluded with
reasons, analysed.

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
