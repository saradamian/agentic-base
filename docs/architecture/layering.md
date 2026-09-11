# Where this sits, and which capabilities get published

## Is this the bottom layer

Yes. Nothing here imports an application, an orchestrator or a serving stack, and nothing here
should. Above it:

| layer | who | what it owns |
|---|---|---|
| applications | agentic-env, products | agents, experiments, domain workflows |
| control plane | AI4Science | job submission, orchestration, tenancy, datasets |
| capability servers | one per system | publishing a system to an agent over a protocol |
| **base layer** | **this** | **contracts, the record, shared primitives** |

## Is it agentic

No, and that is the point worth being clear about. There is no agent in it, no loop, no planner
and no memory. It is what an agent stands on: the tool contract it speaks, the span vocabulary it
emits, the record of what it did, and a handful of primitives that are wrong in expensive ways if
each application writes its own.

The name describes the purpose, not the contents. If that reads as overclaiming, the accurate
alternative is a substrate for agentic systems, which is longer and says the same thing.

## Which capability servers should exist

The useful question is not "how many servers" but "which capabilities should an agent at SURF be
able to reach". Five answer that today, and each wraps exactly one system:

**runs**. What ran, under what configuration, who decided the outcome, and whether a comparison
between two configurations is sound. This is the only one of the five that does not exist
somewhere already, which is why it is the one built here.

**hpc**. Submit a job, watch it, reach a served model. Two curated surfaces exist upstream, one
read-only for operations and one for serving, plus a REST path through the control plane.

**data**. Datasets, artifacts, and where a given file came from. The control plane already has the
vocabulary for this.

**software**. Build recipes and environment modules.

**knowledge**. The wiki, searchable and citable.

A sixth is worth naming because it is the same machinery pointed at a different workload, the
history of *pipeline* runs rather than agent runs. An agent asked to fix a broken pipeline needs
past executions, and that is the records server with a different producer writing into it.

## What the base layer does and does not do about them

It does not implement any of those servers. It provides three things they share:

the tool contract, so a capability has one name whichever backend serves it;

the recording seam, so a served call is journalled, traced and scanned without the layer knowing
what a journal is;

the curated-surface mechanism, so a server publishes a reviewed subset rather than everything a
system can do. Publishing everything costs the caller a schema per turn and hands out capabilities
written for a trusted in-process caller.

That division is what keeps this layer thin. A server that needs a runtime handle belongs with the
runtime; the contract it speaks belongs here.

## What to take from the control plane, and what not to

Take the **vocabulary**. The job, partition, cluster and tier shapes, roughly 400 lines of
schemas. Two vocabularies for a Slurm job already exist between the two repositories, and one of
them has to win before either can be an interface.

Do not take the **orchestration**. Workflow engines are a solved problem and the control plane
already runs one. What is not solved anywhere is the bookkeeping on top: what counts as done, what
must be voided, a timeout that must never be recorded as a result, and the standing suspicion that
exclusions correlate with the condition being tested.

Do not take the **execution seam as it stands**. It passes a user's model credential inside the
text of a submitted job script, on a shared filesystem. That is the first thing to replace, and
replacing it is what makes the two repositories fit together rather than overlap.
