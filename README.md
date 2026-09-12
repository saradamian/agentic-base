# agentic-base

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
| `app.domain.run_record` | one row per run: the transcript the model actually received, the provenance of its environment, and the provenance of its outcome label | experiment trackers record what a run produced; almost none record *who decided* whether it was right, or whether the instrument that decided was working |
| `app.domain.validity` | adjudicates whether a contrast across arms is sound, by detecting exclusion channels whose rate differs by arm | trackers store, version and visualise runs. None of them tell you your comparison is invalid |

The second has a name in the missing-data literature: missingness that is **MNAR with respect to
the treatment arm**. The concept is decades old. No experiment tracker implements it.

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

## Where development happens

Here. Changes land on `main` through pull requests that the gate has passed on both ends of the
supported Python range. SURF's own deployment of this service, the environment overlays and the
internal pipeline definition, is kept apart from this repository because it describes where the
software runs rather than what it does.

## Versioning and releases

Semantic versioning, with the version taken from the git tag. While the major version is `0`, a
minor bump may change the public interface, and the import name of the package is one of the
things that may change before `1.0`. Releases are tagged `vX.Y.Z` and each carries generated
notes and a built distribution. See `CONTRIBUTING.md` for the release procedure.

## Citation

Cite the repository using `CITATION.cff`; GitHub renders it under *Cite this repository*.

## Licence

European Union Public Licence v. 1.2. See `LICENSE`.
