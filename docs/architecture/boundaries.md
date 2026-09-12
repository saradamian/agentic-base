# Boundaries against the neighbouring efforts

There are four adjacent efforts. Confusing them is easy and expensive, so this names the boundary
for each one, in the form of what this repository must never do.

## The neighbours

**Willma** (`the internal Willma repository`) is the AI Hub back office. It serves models and
gives users a shared endpoint. It is live and it has an owner.

**AI4Science PoC** (`the internal AI4Science repository`),
is a job orchestrator: an HTTP API, per-user authentication, Prefect workflows, jobs submitted to
Slurm through its REST API, deployed on Kubernetes. It is a prototype with one author, and it
already submits agent runs as Slurm jobs.

**The AI Factory (NLAIF)** is not a repository. It is the programme that pays for and sets the
requirements: multi-tenancy, sensitive data, audit evidence, an MLOps toolchain, and portability
across the European federation rather than to one vendor's stack.

**The agentic base layer** is the funded work to give SURF agents a common foundation, internal
and external.

## The division, by concern

| owns | must not |
|---|---|
| **Willma**: serving models, shared endpoints, keeping frequently used models loaded | contain agent logic |
| **AI4Science**: job submission, orchestration, tenancy, datasets, artifacts | hold a second agent runtime, or a second record store |
| **this repository**: the agent base layer, and the system of record for what agents did | serve models, or submit jobs |

The rule that decides the third row is lifetime. An orchestrator is a choice, and in three years
it may be a different choice. The corpus of runs, with the provenance of every outcome, is an
asset that has to survive that change. A record store inside an orchestrator dies with it.

## What is in this repository

Two things that are related and are not the same, kept in one repository because one person
maintains both and splitting early costs more than it saves.

### The base layer: a library any agent can use

This is not an agent framework. Applications bring their own agent, whether that is a
commercial SDK, a graph library, or a loop they wrote. What they get here:

- **recording**: `agentic_base.client`, about ten lines at the call site
- **outbound safety**: `agentic_base.security.netsec`, which refuses to fetch internal addresses
- **a structural filter over generated code**: `agentic_base.code_policy`, a cheap pre-filter in front of
  real isolation and never a substitute for it
- **resilience against self-hosted endpoints**: `agentic_base.llm`, including a probe that asks for a
  completion instead of trusting a status code, and a retry policy that recycles the transport
- **cluster facts without credentials**: `agentic_base.hpc.clusters`
- **a value back from a batch job**: `agentic_base.hpc.job_result`
- **the record in the standards**: `agentic_base.provenance`, W3C PROV, OpenLineage and a Process
  Run Crate from one record, each through that standard's own library, with the scorer and its
  authority carried as a declared extension

### The service: the system of record and the referee

- run records with environment and label provenance
- the validity check over a comparison
- epoch declarations, so a code change that alters meaning can be declared and enforced
- a read-only MCP surface so a chat client can ask

### What is not here and is not coming

No agent loop. No planner, memory, skill library or search. Those were measured in the predecessor
project and mostly did not pay; see `docs/decisions.md` D7 for what was measured and what the
honest conclusion is.

No model serving. That is Willma.

No job submission. That is AI4Science, and the seam between the two is the first piece of work
worth doing together.

## The blocks are outside, by construction

The capability blocks an agent calls, hpc, inference, knowledge, data, software, artifacts, are
each their own package with the owner of the system behind them (`blocks.md`). They import this
repository's contracts; nothing here imports a block. A scheduler client in particular does not
belong here, because this repository must not submit jobs.

## Split this repository when, and not before

One package becomes two when someone outside SURF wants the library and does not want the service,
or when the library gains a second maintainer. Until one of those is true, two packages in one
repository is the cheaper arrangement.
