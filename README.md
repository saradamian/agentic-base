# agentic-platform

The platform layer for agentic workloads on SURF infrastructure: **run provenance, comparison
validity, and HPC execution**.

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
