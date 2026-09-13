# Where this sits

## Is this the bottom layer

Yes. Nothing here imports an application, an orchestrator or a serving stack. Above it:

| layer | who | what it owns |
|---|---|---|
| applications | agentic-env, SURF's own service agents | agents, experiments, domain workflows |
| control plane | AI4Science today; the AI Factory's MLOps and meta-scheduler later | job submission, orchestration, tenancy, datasets, triggers |
| blocks | one package per system, owned by that system's team | publishing a system to an agent over MCP, with a client and skills |
| **contracts** | **this repository** | the tool contract, the recording seam, curated surfaces, security primitives, the span vocabulary, the run record and the referee |

The blocks themselves, what exists behind each and the order to build them, are in `blocks.md`.

## Is it agentic

No. There is no agent in it, no loop, no planner, no memory. It is what an agent stands on: the
tool contract it speaks, the span vocabulary it emits, the record of what it did, and a few
primitives that are expensive to get wrong. The name describes the purpose.

## What this layer provides to a block

Three mechanisms every block shares:

- the tool contract, so a capability has one name whichever backend serves it;
- the recording seam, so a served call is journalled, traced and scanned without the layer
  knowing what a journal is;
- the curated-surface mechanism, so a block publishes a reviewed subset rather than everything a
  system can do. Publishing everything costs the caller a schema per turn and hands out
  capabilities written for a trusted in-process caller.

And the vocabulary they share: the span names from the standard packages, the security
primitives, and the run record every call lands in, with the fields the cross-cutting
capabilities write, the principal a call acted for, the classification and isolation tier it ran
under, the approvals it obtained, the redaction applied before the transcript was stored.

A block that needs a runtime handle belongs with the runtime. The contract it speaks belongs here.

## What to take from the control plane, and what not to

Take the vocabulary: the job, partition, cluster and tier shapes, about 400 lines of schemas. Two
vocabularies for a Slurm job exist between the two repositories, and one has to win before either
is an interface.

Do not take the orchestration. Workflow engines exist and the control plane already runs one.
What no engine gives you is the bookkeeping on top: what counts as done, what must be voided, a
timeout that must never be recorded as a result, and the check that exclusions do not correlate
with the condition under test. That bookkeeping is here.

Do not take the execution seam as it stands. It passes a user's model credential inside the text
of a submitted job script, on a shared filesystem. Replace that first; it is the seam that makes
the two repositories fit together instead of overlap.
