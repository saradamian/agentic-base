# Reuse ledger

Every concern gets one of three verdicts. A verdict must rest on a checked fact: the component exists, is maintained, and models the
thing. An impression is not a verdict. "Feels commodity" is not a
verdict, and neither is "we already have one".

| verdict | meaning |
|---|---|
| **ADOPT** | something maintained already does this. Use it. Do not write ours |
| **BRIDGE** | the standard covers the mechanism; we add a thin, named adaptor for our context |
| **BUILD** | nothing models this. It exists because our setting needs it |

A BUILD row carries a **revisit-when** condition, because a justification without an expiry
becomes a superstition.

## SURF internal, first choice

Found by searching the internal GitLab. These are first-choice because they are already run,
already supported, and already have an owner.

| concern | component | verdict |
|---|---|---|
| source, CI/CD, package registry | GitLab (`the internal GitLab`) | ADOPT |
| pipeline definitions for a Python service | `sdp/components/pipelines/python-application` | ADOPT. This repo's entire CI is four lines because of it |
| container and Helm registry | Harbor (`the internal registry`), via `sdp/components/docker`, `sdp/components/helm` | ADOPT |
| dependency vulnerabilities and SBOM | Dependency Track, via `sdp/components/dependency-track` | ADOPT |
| dependency updates | Renovate, via `sdp/apps/renovate-runner` | ADOPT |
| service catalogue, docs portal, tenant self-service | Backstage (`sdp/apps/backstage`) + TechDocs | ADOPT |
| Kubernetes, namespaces, quotas, policy | SDP clusters, Gatekeeper, `sdp/infrastructure/tenant-template` | ADOPT |
| metrics, logs, dashboards | Prometheus, Grafana, Loki (platform-provided) | ADOPT |
| API gateway | Kong | ADOPT |
| relational storage | PostgreSQL as a tenant resource | ADOPT |
| object storage | MinIO as a tenant resource; SRAM S3 where tenancy follows SRAM | ADOPT |
| secrets | SDP secret management, per its guide | ADOPT. It is the fix for secrets-in-job-scripts |
| identity and collaboration groups | SURFconext, SRAM | ADOPT |
| shared model inference | Willma (`research/hpml/willma`, the AI Hub back office) | ADOPT where it serves the model needed |
| Slurm access from services | `snellius/pyslurm`, `SOIL/slurm-bridge`, Slurm REST | ADOPT. Evaluate both before writing a third |
| software environments on HPC | EasyBuild (`easybuild-surf`), EESSI | ADOPT |

## External, where SURF has no internal equivalent

| concern | component | verdict |
|---|---|---|
| span vocabulary for agents, tools, models | OpenTelemetry GenAI conventions plus OpenInference | ADOPT. Pin a version: they moved to a dedicated repository in June 2026 and have no stable schema URL |
| experiment tracking and GenAI trace UI | MLflow | ADOPT. Note it is not yet an SDP component, so adopting it means proposing it as one |
| data and workflow provenance formats | W3C PROV, RO-Crate, OpenLineage, Croissant | ADOPT. Emit the standards, never a private format |
| inference engine | vLLM | ADOPT |
| reproducible agent benchmarking | HAL | ADOPT as the harness. It has three execution backends, none of them HPC, which is where we bridge |
| rollout / RL training | verl, SkyRL, Agent Lightning | ADOPT as trainers |
| agent security taxonomy | OWASP Top Ten for Agentic Applications, and for agentic skills | ADOPT as the conformance target |
| retry and backoff | tenacity | ADOPT |

## Build, and only these

| concern | why nothing else does it | revisit when |
|---|---|---|
| **run record with label and instrument provenance** | trackers record outcomes, not who decided them or whether the decider was working. A corpus that cannot name its scorers can be neither cited nor trained on | a tracker adds a first-class evaluator-provenance field |
| **comparison validity** | no experiment tracker adjudicates whether a contrast is sound. The statistics is old; the tooling does not exist | any tracker ships arm-correlated missingness detection |
| **agentic execution on batch-scheduled HPC** | the published position is that rollout training does not work on Slurm, for four named reasons: no service discovery, jobs must terminate, no component-level recovery, no dynamic scaling. A national facility cannot leave Slurm | Slurm grows service-level primitives, or the workload moves to Kubernetes |
| **cross-replica request placement** | **ADOPT on Kubernetes.** The Endpoint Picker in the Gateway API Inference Extension routes on queue depth, KV-cache utilisation, prefix-cache locality and adapter affinity, which is the same signal set we arrived at independently. Build only where there is no cluster to run it on | already the case wherever Kubernetes is available |
| **the join across planes** | tying a trajectory to the replica that served it, the weights that produced it and the bytes it read, keyed on content hashes. Each plane's tooling knows its own plane only | an exporter publishes the join, at which point delete ours |
| **energy as a first-class axis** | tokens price an API, GPU-seconds price an allocation, joules are physical. A run that spends more wall clock on the same accelerators emits no extra tokens and still costs more | scheduler accounting exposes per-job energy reliably everywhere we run |

## The rule this file encodes

A private copy of a shared concern does not fail loudly. It drifts, and the drift surfaces as a
measurement artifact somewhere far from the copy. When a row here says ADOPT and our code does it
anyway, that is a defect, not a preference.

## Checked against the world, 2026-09-11

Five verdicts above were re-examined against what is actually published. Four moved, and one of
them moved against us, which is the reason this section exists rather than a quiet edit.

**A label's source is not our idea.** MLflow's assessment model already attaches a source to every
judgement, typed as human, LLM judge, or code. The claim that nobody records label provenance was
wrong and is withdrawn. What survives is narrower and still load-bearing: that taxonomy separates
judgements by *modality*, so a convenience checker and a benchmark's authoritative harness are
both `CODE` to it, and on our own corpus those two disagreed in both directions with roughly a
quarter of the disagreements running in the flattering direction. Modality cannot tell you whether
a number may be cited. The field is also optional, and optional provenance is not supplied, which
is an argument by analogy rather than a measurement of MLflow: the corpus where 4,742 of 10,920
outcomes named no scorer was produced by *our* optional field, not theirs. So `LabelAuthority` is a **BRIDGE**, not a **BUILD**,
and `mlflow_source_type` exists so a record exports into their schema instead of a private one.

**HAL is the complement, not the competitor.** It went to ICLR 2026 on 21,730 rollouts and
independently found scaffold choice multiplying cost roughly tenfold, which corroborates our
inversion result rather than pre-empting it. The division is clean: HAL varies the model and holds
the scaffold, we vary the scaffold and hold the model. It standardises a harness, which works when
you own the harness and stops working when tenants bring their own; that is what the arm
fingerprint is for. ADOPT stands, and we cite them rather than claim the territory.

**The agentic serving profile has been published by someone else.** There is now work on KV cache
management for serving coding agents specifically. "Agentic inference is a distinct prefill-heavy
workload" is no longer ours to claim. What remains ours is cross-replica placement on bare-metal
Slurm, which every upstream implementation assumes Kubernetes for, and the acceptance argument
that throughput is non-monotonic in concurrency so utilisation scores the collapse as healthy.

**The GenAI conventions are still Development, in their own repository, on their own cadence.**
Not one attribute is marked stable. Read as a reason to wait, that is wrong; it is the window in
which proposals land. Two attributes would carry most of our argument into a standard other people
implement: one naming the scaffold identity that produced a trace, one naming the authority of an
outcome label rather than only its modality. Neither is a new standard.

**One thing to carry to the procurement that we did not have.** Evaluation is being discussed as a
compute bottleneck in its own right. The acceptance suite has no agentic workload, which was
already remark A1, and no evaluation workload either, which nobody had noticed.


## The open question this ledger has not answered

The ledger says **ADOPT MLflow** and this repository still carries its own run store. The
vocabulary is bridged; the storage is not. That is a gap between a verdict and the code, and it is
recorded here rather than left as an intention.

The test for keeping a store you have been told to replace is whether the thing you keep does
something the thing you would adopt cannot. Here it does: MLflow cannot express *this label came
from a checker whose false-fail rate differs several-fold across arms and must never be differenced
against another arm's*. That is a schema property, and a schema gap cannot be bridged by writing
into an optional free-text field.

But the sharper question is whether the **store** is load-bearing or only the **write-path rule**.
One could adopt MLflow's storage and still refuse a write that does not name a scorer, enforcing
at our boundary and persisting through theirs. Three things decide it, and all three are
measurable rather than arguable:

1. Does the refusal survive the round trip, or can a client write past it?
2. Can the authority vocabulary be reconstructed on read?
3. **Can a reader tell a reconstructed authority level from a natively stored one?** If it cannot,
   the vocabulary has survived in form and not in force, which is the failure that looks most like
   success.

If all three hold, the store goes and the rule stays, and the ledger is satisfied without losing
the part that matters. If any fails, there is a written reason to keep the store, which is what
the ledger actually wants. Until that is measured, this section is the honest statement of where
the repository stands.
