# surf-agentic-base

[![ci](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml/badge.svg)](https://github.com/saradamian/agentic-base/actions/workflows/ci.yml)
[![licence: EUPL-1.2](https://img.shields.io/badge/licence-EUPL--1.2-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%20to%203.14-blue.svg)](pyproject.toml)
[![cite](https://img.shields.io/badge/cite-CITATION.cff-green.svg)](CITATION.cff)

The agentic base layer for SURF: **run provenance, comparison validity, and the shared
primitives an agent needs**.

It is built on the SURF Developer Platform golden path and adopts the common stack wherever the
common stack has an answer. It contains only the parts we could not find anywhere else.

## The problem it addresses

Agent runs are a fourth execution pattern beside training, fine-tuning and inference: a long-lived
loop that consumes inference and executes code. They are expensive, hard to reproduce, and easy to
report wrongly. This service records what actually ran with enough provenance to replay it and to
audit it, adjudicates whether a comparison between two configurations is sound enough to publish,
and drives execution on batch-scheduled HPC where the usual cloud-native answers do not reach.

## Adopted, not written here

It does not ship an agent framework, a tracing backend, a metrics store, a dashboard, an experiment
tracker, a workflow engine, or an inference server. Every one of those exists and is better than
anything we would write. See [the reuse ledger](docs/architecture/reuse-ledger.md) for what is
adopted and from where.

## The two modules that are the reason it exists

| module | what it does | why nothing off the shelf does it |
|---|---|---|
| `agentic_base.domain.run_record` | one row per run: the transcript the model actually received, the provenance of its environment, and the provenance of its outcome label | experiment trackers record what a run produced; almost none record *who decided* whether it was right, or whether the instrument that decided was working |
| `agentic_base.domain.validity` | adjudicates whether a contrast across arms is sound, by detecting exclusion channels whose rate differs by arm, and reports the per-arm accounting behind the verdict | trackers store, version and visualise runs. None of them tell you your comparison is invalid, and no reporting standard in agent evaluation asks for the accounting that would show it |

Neither is exported in a private format. `agentic_base.provenance` turns one record into W3C
PROV, an OpenLineage run event and a Process Run Crate, each through that standard's own library,
with the scorer and its authority carried as a declared extension whose schema is in
`docs/schemas/`.

The second is not a new mechanism, and the README used to overclaim it as one. Clinical trials
have shipped exactly this artifact for two decades: the **CONSORT flow diagram**, a per-arm
accounting of everyone who left the denominator and why, mandatory for publication since 2001,
with an extension for AI interventions since 2020. The defect it exposes has a name in the
missing-data literature, missingness that is **MNAR with respect to the treatment arm**. What is
missing is not the idea. No experiment tracker implements the check, and no reporting standard in
agent evaluation requires the accounting, so `validity` implements the check and
`flow_by_arm` produces the accounting in the standard's vocabulary: assessed, excluded with
reasons, analysed.

## Running locally

```bash
just run          # uvicorn with reload on :8080
just check        # tests with coverage, ruff, mypy
```

SQLite by default so it runs with no infrastructure. PostgreSQL, provided as a platform tenant
resource, in every deployed environment.

## Documentation

- [Reuse ledger](docs/architecture/reuse-ledger.md): adopt, bridge, or build, with the reason
- [What came from agentic-env](docs/architecture/from-agentic-env.md): what was extracted and what was left
- [Going live on SDP](docs/architecture/go-live-on-sdp.md): the onboarding path and the one open question

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
consumer of a web template already has. Releases are tagged `vX.Y.Z` and each carries generated
notes and a built distribution. See `CONTRIBUTING.md` for the release procedure.

## Citation

Cite the repository using `CITATION.cff`; GitHub renders it under *Cite this repository*.

## Licence

European Union Public Licence v. 1.2. See `LICENSE`.
