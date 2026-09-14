# Reuse ledger

Every concern gets one of three verdicts. A verdict must rest on a checked fact: the component
exists, is maintained, and models the thing. An impression is not a verdict. "Feels commodity" is
not a verdict, and neither is "we already have one".

| verdict | meaning |
|---|---|
| **ADOPT** | something maintained already does this. Use it. Do not write ours |
| **BRIDGE** | the standard covers the mechanism; we add a thin, named adaptor for our context |
| **BUILD** | nothing models this. It exists because our setting needs it |

A BUILD row carries a **revisit-when** condition, because a justification without an expiry
becomes a superstition.

## SURF internal, first choice

Found by searching SURF's own repositories. These are first-choice because they are already run,
already supported, and already have an owner.

| concern | component | verdict |
|---|---|---|
| source, CI/CD, package registry | GitLab, SURF's own instance | ADOPT |
| pipeline definitions for a Python service | the Developer Platform's pipeline component for Python applications | ADOPT for the deployment. The public repository cannot run it, so `.github/workflows/ci.yml` runs the gate's commands from `CONTRIBUTING.md` plus a lock check, and the deployment overlay carries the SDP one. Two pipelines for one gate is a P1 tension, named here so it is not mistaken for a choice; the commands are one list in `CONTRIBUTING.md` |
| container and Helm registry | Harbor, through the platform's container and Helm components | ADOPT |
| dependency vulnerabilities and SBOM | Dependency Track, through the platform's component | ADOPT |
| dependency updates | Renovate, the platform's runner | ADOPT |
| service catalogue, docs portal, tenant self-service | Backstage with TechDocs, the platform's | ADOPT |
| Kubernetes, namespaces, quotas, policy | the platform's clusters, Gatekeeper, its tenant template | ADOPT |
| metrics, logs, dashboards | Prometheus, Grafana, Loki (platform-provided) | ADOPT |
| API gateway | Kong | ADOPT |
| relational storage | PostgreSQL as a tenant resource | ADOPT |
| object storage | MinIO as a tenant resource; SRAM S3 where tenancy follows SRAM | ADOPT |
| secrets | SDP secret management, per its guide | ADOPT. It is the fix for secrets-in-job-scripts |
| identity and collaboration groups | SURFconext, SRAM | ADOPT |
| shared model inference | Willma, the AI Hub back office | ADOPT where it serves the model needed |
| Slurm access from services | slurmrestd, the scheduler's own REST API with a published OpenAPI specification, plus a thin site wrapper. Surveyed 2026-09-13: three hand-written REST clients exist at SURF (willma2, the AI4Science prototype, an internal stub) and one SSH backend (agentic-env) | ADOPT the REST API and generate the client from its specification; the wrapper is one package in the **hpc block**, not this repository (`blocks.md`) |
| software environments on HPC | EasyBuild, SURF's easyconfigs, EESSI | ADOPT |

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
| dependency advisories on the public repository | GitHub's dependency review, `pip-audit` (Apache-2.0) over the exported lock, and Renovate through its GitHub app | ADOPT. They cover what Dependency Track covers on the platform, for the repository the platform does not build |
| credential scanning of files and history | gitleaks (MIT), as willma2 runs it | ADOPT, with one rule added for a key in the shape a SURF service issues: measured, gitleaks misses it, and GitHub's generic patterns need paid Secret Protection. The rule is the redaction layer's own pattern, and a test holds the two together. The binary is pinned by version and checksum rather than the action, which needs a licence key for an organisation-owned repository |
| personal-data detection and redaction | a language model on Willma for people and places, GLiNER (Apache-2.0) as the fallback, patterns for the rest. Microsoft Presidio was adopted and then removed | ADOPT GLiNER; the rest is in the source audit below. Presidio is not adopted: with names from a model its remaining job is patterns, and for that it brings spaCy, 56 packages and 285 MB, and its anonymizer pins cryptography below a release with six advisories |

## Build, and only these

| concern | why nothing else does it | revisit when |
|---|---|---|
| **run record with label and instrument provenance** | trackers record outcomes, not who decided them or whether the decider was working. A corpus that cannot name its scorers can be neither cited nor trained on | a tracker adds a first-class evaluator-provenance field |
| **comparison validity** | no experiment tracker adjudicates whether a contrast is sound, and we found no reporting standard in agent evaluation that asks for the per-arm accounting that would show it. The check is ours; the accounting is CONSORT's flow diagram, adopted as a standard below rather than reinvented | any tracker ships arm-correlated missingness detection, or an agent-evaluation reporting standard mandates a per-arm exclusion flow |
| **agentic execution on batch-scheduled HPC** | the published position is that rollout training does not work on Slurm, for four named reasons: no service discovery, jobs must terminate, no component-level recovery, no dynamic scaling. A national facility cannot leave Slurm | Slurm grows service-level primitives, or the workload moves to Kubernetes |
| **cross-replica request placement** | **ADOPT on Kubernetes.** The Endpoint Picker in the Gateway API Inference Extension routes on queue depth, KV-cache utilisation, prefix-cache locality and adapter affinity, which is the same signal set we arrived at independently. Build only where there is no cluster to run it on | already the case wherever Kubernetes is available |
| **the join across planes** | tying a trajectory to the replica that served it, the weights that produced it and the bytes it read, keyed on content hashes. Each plane's tooling knows its own plane only | an exporter publishes the join, at which point delete ours |
| **energy as a first-class axis** | tokens price an API, GPU-seconds price an allocation, joules are physical. A run that spends more wall clock on the same accelerators emits no extra tokens and still costs more | scheduler accounting exposes per-job energy reliably everywhere we run |

## Standards adopted as standards

Not every reuse is a package. These are reporting standards whose vocabulary and mandatory
artifacts we adopt, because a reader from that field should recognise what they are looking at.

| concern | standard | verdict |
|---|---|---|
| per-arm accounting behind a contrast | **CONSORT** (2001; 2010 revision), the flow diagram: assessed, excluded with reasons, analysed, per arm. **CONSORT-AI** (2020) is the extension for AI interventions | ADOPT the vocabulary and the artifact. `agentic_base.domain.validity.flow_by_arm` produces it; `ValidityReport.flow` carries it. The only PyPI package named `consort` is a music-notation tool, so there is nothing to install |
| intention-to-treat vs per-protocol | CONSORT's two analysis populations | ADOPT as the names for the full split and the paired set. `paired_items` is per-protocol and is the wrong denominator for a score for exactly the reason CONSORT gives |

## Source audit

Every module under `src/agentic_base/` checked against the question this file exists to ask: does
something maintained already do this? `tests/test_reuse_ledger.py` fails when a module has no row.

| module | finding | verdict |
|---|---|---|
| `observability/conventions.py` | imports `openinference-semantic-conventions` and the OpenTelemetry incubating `gen_ai` attributes, with literal fallbacks when neither is installed | ADOPT, as the row above says. Pin the versions |
| `observability/tracing.py` | the SDK's FastAPI instrumentation and an exporter chosen by the standard `OTEL_*` variables | ADOPT. Nothing here is a private knob; the one decision of ours is that no endpoint means record-and-drop rather than a default address nobody listens on |
| `utils/logging.py` | structlog plus `asgi-correlation-id`, from the golden-path template | ADOPT |
| `llm/resilience.py` | retry predicates and a transport pool; the loop belongs to tenacity | ADOPT, correctly split |
| `mcp/server.py` | the official `mcp` SDK, 2.x, in the `service` extra: framing, handshake, transports and tracing are the SDK's. Ours are the four tools, the pure dispatch, and the observer seam run as the SDK's own middleware, applying a result rewrite to the structured copy as well as the text; a tool error is raised so the SDK marks it, and a long transcript is served in pages whose size the deployment and the caller set | ADOPT. It hand-rolled the protocol for a week while this row said ADOPT, which is what the ledger test now catches |
| `code_policy/policy.py` | an AST pre-filter, deliberately not an isolation boundary. **RestrictedPython** (8.5, 2026-08, `>=3.10`) covers the runtime half, guarded builtins and attribute access, and has been attacked for twenty years | BRIDGE. Keep the zero-dependency pre-filter in the library half; any executor added to this repository adopts RestrictedPython for the runtime guard rather than extending this file |
| `security/netsec.py` | SSRF validation and DNS pinning. The one wrapper that did this, `advocate`, last released 2020-07 and targets `requests` | BUILD. Revisit when httpx ships an SSRF-safe transport or a maintained library appears |
| `hpc/job_result.py` | a delimited single-line base64 result channel over Slurm stdout | BUILD. Nothing models a value coming back from a batch job. Revisit when Slurm exposes a result channel |
| `domain/validity.py` | see the standards table | BUILD the check, ADOPT the standard. Revisit when the build table's row for comparison validity says to |
| `auth.py` | bearer tokens mapped to the tenants each may use, checked on every data route, refusing by default | BRIDGE: FastAPI's `HTTPBearer` carries the scheme; the tenant grants are ours, because no platform component yet says which tenants a caller may write. Revisit when the gateway passes a verified identity with tenant claims from the federation, and check the claim instead of a token |
| `client.py` | an httpx client for the service's write path, one call per record | ADOPT httpx. The ten lines around it are the call site, not a client library |
| `config.py` | `pydantic-settings` over environment variables | ADOPT |
| `db.py` | engine and session from SQLModel | ADOPT |
| `limits.py` | a settings object read through a cached accessor | ADOPT `pydantic-settings`. The accessor is the fix for import-time constants and is ours |
| `main.py` | FastAPI, the Prometheus instrumentator, correlation ids, structlog | ADOPT, all from the golden-path template |
| `routers/health.py` | liveness and readiness | ADOPT, template |
| `routers/runs.py` | the write path that refuses an outcome without a scorer, the validity endpoint, a run served in any of the three provenance standards, the endpoint that records an approval, and a tenant's corpus as one export | BUILD. Measured 2026-09-12: MLflow accepts an unsourced outcome from any client and stamps it `CODE/default`, so the refusal has to live at a boundary of ours. Revisit when a tracker refuses an unsourced outcome at its own API |
| `recording.py` | the observer seam a served call passes through | BRIDGE. `mcp` 2.x ships `ServerMiddleware`, the same seam for that transport; `mcp.server.ObservingMiddleware` adapts ours through it, so a host implements one observer and every served call reaches it |
| `domain/run_record.py` | the table behind the BUILD row above | BUILD, see the build table. Revisit when that row says to |
| `domain/outcomes.py` | the label vocabulary, the rules over a structural protocol, and the fields the cross-cutting capabilities write: principal, classification, isolation tier, redaction, approvals, disclosure, content marking | BRIDGE onto MLflow's assessment source for the label; see the store question below. The other fields are ours: no tracker has a place for who approved what, what class of data a run touched, or whether a person was told they were dealing with an AI |
| `domain/epochs.py` | declaring that a revision changed a field's meaning, and refusing to pool across it | BUILD. No tracker records a dependency version as a pooling key. Revisit when one does |
| `domain/retention.py` | how long a transcript is kept, the AI Act's six-month floor as a refusal rather than a clamp, and an erasure that empties the transcript and leaves everything the hash chain covers | BUILD. The two regimes are reconcilable only against this record's own shape: which fields are personal and which are evidence. Revisit when the platform offers retention as a tenant resource |
| `domain/audit.py` | the log the service appends to on every create, label and approval: a snapshot of the audit fields, chained per tenant, with a unique constraint that makes a fork impossible, and the check that compares each run to its latest entry | BUILD, for the same reason as the chain below: a snapshot per change is what lets an outcome attached later stay verifiable. Revisit when the store moves to a database with native tamper evidence, and delete it with the chain |
| `domain/integrity.py` | a hash chain over audit fields, `hashlib` only | BUILD, deliberately modest. Revisit when the store moves to a database with native tamper evidence, at which point delete this |
| `hpc/clusters.py` | cluster facts as YAML data with a no-secrets guard | ADOPT PyYAML and pydantic; the profile schema is ours and small |
| `llm/health.py` | a probe that asks for a completion rather than trusting a status code | BUILD. Revisit when vLLM or Willma expose a readiness signal that means "answers", not "listens" |
| `provenance/emit.py` | W3C PROV through `prov`, OpenLineage through `openlineage-python`, a Process Run Crate through `rocrate`; the outcome's scorer and authority ride as declared extensions with a schema file each | ADOPT the three libraries and the profile. The facet is a BRIDGE, and `docs/schemas/OutcomeRunFacet.json` is its contract |
| `provenance/mlflow_export.py` | a run as an MLflow trace plus a feedback assessment, through MLflow's own client with an explicit experiment, every record field as a span attribute, idempotent by a run-id tag, and a command that exports a tenant; the authority rides in assessment metadata because the schema has no field for it | ADOPT MLflow for the trace UI and as an export target; the metadata keys are the BRIDGE. Revisit when MLflow's assessment source carries authority natively |
| `redaction/redact.py` | the seam: which transcript fields are text, span replacement, that the record names every instrument that ran and how much it examined, and that a writer's own redaction is not overwritten | BUILD, deliberately small. No redaction library knows a run record's shape. Revisit when the record's transcript is stored in a standard message format a redactor already walks |
| `redaction/patterns.py` | credentials, contact details, IBAN, card numbers, IP addresses and the Dutch citizen service number, by shape and checksum, standard library only; the credential set merges agentic-env's two corpus scanners | BUILD. Presidio does this and pulls in spaCy, 56 packages and 285 MB, for a names layer we do not use; detect-secrets covers credentials only. Revisit when a maintained, dependency-light library covers both |
| `redaction/llm.py` | people and places from a model behind an OpenAI-compatible endpoint, over httpx with `llm.resilience`'s retry rules; JSON-schema output, fenced input, pieces, cooldown | BRIDGE: the endpoint is Willma's, the protocol is OpenAI's. Presidio's LangExtract path was not taken because it adds a library for one request shape |
| `redaction/gliner.py` | the fallback: a GLiNER PII model in process, GPU when present | ADOPT GLiNER. The capitalisation filter on person spans is ours, because the model tags role nouns as people |
| `redaction/layered.py` | patterns always, masking before a model sees the text, primary then fallback, closed when neither answers | BUILD. The fail-closed rule is a property of the record, not of any detector. Revisit when the platform offers a redaction service with the same guarantee |
| `redaction/configured.py` | the service's redactor built from `pydantic-settings`, once | ADOPT `pydantic-settings` |
| `tools/types.py` | the in-process tool contract | BRIDGE. `mcp.types.Tool` is the wire schema; this is the in-process one it is derived from, and the names must match across backends (D1) |

## The rule this file encodes

A private copy of a shared concern does not fail loudly. It drifts, and the drift surfaces as a
measurement artifact somewhere far from the copy. When a row here says ADOPT and our code does it
anyway, that is a defect, not a preference.

## Checked against the world

Verdicts above are re-examined against what is published, and a verdict that moves is recorded
here with its reason rather than edited quietly. Two of the moves went against us.

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

**One thing to carry to the AI Factory's requirements.** Evaluation is being discussed as a
compute bottleneck in its own right. The acceptance suite has no agentic workload and no
evaluation workload either; `cross-cutting.md` says so as its sixth sentence.

**MCP moved under us.** The SDK went to 2.x for the 2026-07-28 protocol, with OpenTelemetry
tracing on by default and an in-memory client for tests. This repository serves on it, in the
service extra; the four tools and the pure dispatch are what remain ours. Two consequences: the SDK traces through the API's global
provider, so `configure_tracing` sets it, and a test proves an SDK span reaches the exporter; and
the recording seam runs as the SDK's own `ServerMiddleware`, so the `recording.py` row's BRIDGE
is real rather than intended.

**The AI Act dates moved; the requirement did not.** The Digital Omnibus defers the Annex III
high-risk obligations to 2 December 2027 and Annex I to 2 August 2028. GPAI provider duties and
the Commission's enforcement powers stay on 2 August 2026. `integrity.py` and `compliance.md` say
so.

**The Dutch Cybersecurity Act is live.** In force 15 August 2026; the intended date for higher
education is March 2027.

**The Cyber Resilience Act's reporting duty started on 11 September 2026.** Whether it reaches
this package is open, and `compliance.md` says what either answer would ask for.

**RestrictedPython had a complete sandbox escape** (positional-only parameters, fixed in 8.3). It
does not change the BRIDGE verdict, and it is the reason the pre-filter's docstring says what it
says: nothing at this layer is an isolation boundary.

**The GenAI conventions are Development, in their own repository, on their own cadence.** Not one
attribute is marked stable. Read as a reason to wait, that is wrong; it is the window in which
proposals land. Both vocabulary packages are pinned in the service extra, so the
literal fallbacks are not what runs in the suite, and a test holds every fallback literal to the
installed value. The two attributes this repository keeps carrying as extensions, scaffold
identity and label authority, are written up in `proposals.md`, ready to file. The venue is the
Linux Foundation's Agentic AI Foundation, where MCP and the conventions now live, not a private
schema.

## The store question, measured 2026-09-12

The ledger says **ADOPT MLflow** and this repository carries its own run store. Whether the
*store* is load-bearing, or only the *write-path rule*, was left as three measurable checks. They
were run against MLflow 3.16 with a SQLite backend, using MLflow's own client, and the script is
one screen long.

| check | result |
|---|---|
| 1. Does a refusal at our boundary survive the round trip, or can a client write past it? | **A client writes past it.** `log_feedback` with no source is accepted and the store records `source_type=CODE, source_id=default`. The SDK's own default supplies the scorer the caller did not |
| 2. Can the authority vocabulary be reconstructed on read? | **Yes.** Carried in assessment metadata under `agentic_base.*` keys, it comes back intact, and the two modalities that collapse to `CODE` are told apart by it |
| 3. Can a reader tell a reconstructed authority from a natively stored one? | **No.** There is no native field, and an assessment written by a raw client with the same metadata is byte-identical in every field the store exposes. The store records no writer identity |

So the store stays, and the reason is now a measurement rather than a preference: the property
this platform exists to guarantee, that an outcome cannot be recorded without naming its scorer,
is enforced at exactly one place, and MLflow's API is not that place. MLflow remains ADOPT for
what it is good at, the trace UI and the export target, through `mlflow_source_type`. Revisit
when MLflow makes the assessment source mandatory at the API and records who wrote it, since
both of the failing checks would then pass.
