# Logging, security, safety and compliance

Where each of these lives, what this repository provides for it, what a block must do, and what
the platform provides. Then the obligations, regime by regime, and what each one asks of an agent
platform. Then what the vision should say that it does not say yet.

Scope note: engineering, not legal advice. Whether a given use case is in scope of a regime is
for counsel and the compliance officer.

## Where each concern lives

| concern | this repository | every block | the platform |
|---|---|---|---|
| **logging** of what an agent did | the run record: the transcript the model received, the environment, the outcome and who decided it, written while the run happens. Structured JSON logs with a correlation id. Every served call passes the recording seam | records every call through the seam; emits spans under the standard vocabulary so one trace spans blocks | Loki, Prometheus, Grafana; the OTLP collector; retention of the log stores |
| **security** against misuse of the blocks | outbound URL check with DNS pinning; the structural pre-filter on generated code; curated surfaces so a block publishes a reviewed subset; token redaction on error strings | publishes only its curated surface; scopes it by the caller's identity; carries the platform's isolation tier in its profile | SURFconext and SRAM; secret management; network policy and admission control; the container image scan; Dependency Track |
| **safety** of what an agent produces | the label authority and the degraded flag, so a verdict cannot be cited unless a working authoritative scorer produced it; the validity check, so a comparison cannot be reported when its exclusions correlate with the arm | the execution block runs generated code behind a real boundary; the channels block does not send on someone's behalf without approval | the isolation tiers; confidential computing for the sensitive partition |
| **compliance** evidence | the hash chain over audit fields, which detects an edit and is neither a signature nor an append-only store; provenance in W3C PROV, OpenLineage and RO-Crate; `compliance.md` maps obligations to what exists | keeps the evidence a regime asks for as a by-product of running, not a report assembled later | ISO 27001 certification of the HPC services; the baseline information security standard every SURF service meets; the audit function |
| **engineering practice** | `ENGINEERING.md`: every rule names the test that fails when it stops holding; signed tags, attested wheels and SBOMs; dependency review and audit on every change | starts from the template and inherits the standard | the Developer Platform's pipeline components, GitOps, the developer portal |

## The four gaps, set in the structure

Each of these was a gap in the first version of this page. None has a full solution today. All
four are now fields on the record, with defaults that keep every existing writer working, so a
corpus recorded from now on can say which runs predate the solution, and a solution has a place
to write to when it arrives.

| gap | in the structure now | what fills it later | AI Factory area it belongs to |
|---|---|---|---|
| nothing redacts personal data before a transcript is written | `redaction` on every run: `none`, or the instrument's name and version. A transcript with `none` and a personal classification is a finding | Presidio at the recording seam, in the ledger as ADOPT-when-built | the LLM sandbox with safety filters and logging; data governance |
| no record says what class of data a run touched; sensitive data is the AI Factory's central commitment | `classification` on every run, six levels from unclassified to health, and `isolation_tier`. One rule already enforced: personal or health data cannot have run on the community tier | the tenant's use case sets both; the execution block reads them to pick the tier | data governance; the sandbox architecture with its isolation and access policies |
| no block demands a delegated credential | `principal` on every run: the person it acted for, empty for a service identity. Recorded so the corpus can separate the two populations | scoped, expiring credentials issued by the federation and demanded by every block | user access; the identity federation the platform already runs |
| no human oversight record; the AI Act's article 14 expects one for high-risk systems | `approvals` on every run, each with action, decision, who and when, and an endpoint to add one | the channels and forge blocks write one before a write, a submission or a send | evaluation and compliance: the logging, evidence and audit infrastructure |

## The obligations, and what each asks of an agent platform

### AI Act

The general-purpose model obligations have applied since August 2025 and the Commission's
enforcement powers since August 2026. The high-risk obligations moved to December 2027 for
standalone systems and August 2028 for systems embedded in regulated products. Whether an agent
built on the platform is high-risk depends on what it is used for, so the platform has to make
the high-risk evidence cheap to produce without assuming every run needs it.

| asks for | what it means for agents | lands in |
|---|---|---|
| automatic recording of events over the system's lifetime, kept at least six months | every run, every tool call, every outcome, with who decided it, written at the time | runs; the recording seam; retention enforced by the platform |
| technical documentation and declared performance | the configuration fingerprint, the model, the instrument and its authority on every record; the validity check before a number is reported | runs |
| human oversight | a person can approve, override or stop, and the record shows that they did | approval, on the runs record; not modelled yet |
| transparency: a person knows they are dealing with an AI, and generated content is marked | the channels block says so on every outbound message | channels; not modelled yet |
| regulatory sandboxes with evidence | a tenant whose runs are recorded with the classification and the isolation tier they ran under | runs plus execution |

### GDPR, and the Dutch implementation

The platform is a processor for the tenants that bring personal data, and the questions users
already ask are the processor's: a processing agreement, EU-only residency, no operator access
from outside the EU, what the operator can see.

| asks for | what it means for agents | lands in |
|---|---|---|
| purpose limitation and data minimisation | a run records what it needs to replay and audit, and nothing else; transcripts are the hard case | runs; redaction at the seam, not built |
| a record of processing, and the right to erasure | a run can be found by the person whose data it touched, and deleted, with the chain saying so | runs; deletion is detectable and not modelled |
| pseudonymisation where appropriate | personal data is replaced before it reaches a model or a record | the seam; Presidio or equivalent, not adopted yet |
| what the operator can see | the platform's own staff are a party the design has to name | identity; platform |

### NIS2 as the Dutch Cybersecurity Act, in force since 15 August 2026

Ten risk-management measures and a reporting clock: early warning within 24 hours, notification
within 72, final report within a month. The clock is the requirement. It is meetable only if the
evidence exists when the incident is found.

| asks for | what it means for agents | lands in |
|---|---|---|
| logging that stands up afterwards | who did what, through which block, with which credential, when; intact | runs, the hash chain, identity |
| incident handling | a path from detection to a report; the platform's, drawing on the record | platform |
| supply-chain security and vulnerability handling | pinned actions, attested wheels, an SBOM per release, dependency review and audit on every change, an image scan on every build | this repository; the platform pipeline |
| access control and multi-factor authentication | the federation's; an agent never holds a credential wider than the person it acts for | identity; delegated credentials, not built |

### ISO 27001, the baseline every SURF service meets

SURF's HPC services are certified and the AI Factory has to keep that certification, and every
SURF service meets the baseline information security standard. The controls that touch an agent
platform, with the 2022 numbering: logging and monitoring (8.15, 8.16), privileged access and
access rights (8.2, 5.18), information classification and labelling (5.12, 5.13), data masking
and leakage prevention (8.11, 8.12), information deletion (8.10), configuration management (8.9),
secure development and change management (8.25 to 8.32), supplier security and the cloud
services clause (5.19 to 5.23), incident management (5.24 to 5.28), web filtering (8.23),
cryptography (8.24), threat intelligence (5.7).

What that means for the blocks: every call is logged with the acting identity; egress is
filtered and logged; generated code runs under a declared isolation tier; data carries a
classification the block enforces; suppliers, which here means every adopted dependency and
every model endpoint, are on record with a version; the run record is the audit trail for the
whole set.

### NEN 7510, the healthcare extension

Health use cases ask for it. The position SURF works from: ISO 27001 suffices unless SURF itself processes, stores or
enriches patient data on a hospital's behalf; if it does, NEN 7510 applies and adds
healthcare-specific controls, of which the ones that bite here are logging of every access to
patient data at record level, and separation of duties for whoever operates the platform. Two
further asks come with that: an assurance statement (ISAE 3000 type 2) for the parties
involved, and a confidentiality, integrity and availability level defined per use case, with
measures matched to it. A medical-device question hangs over any use case where the output
guides care.

For the blocks that is one design consequence: the classification of a use case selects the
isolation tier, the logging depth and the retention, and it is set per tenant and per run, not
chosen by the agent.

### BIO, for government tenants

The Dutch government baseline applies to the public-sector users the Factory expects. It is ISO
27001 with mandatory measures, so it adds nothing structural beyond the above, but it removes
optionality: the measures above are required, not recommended, for that tenant class.

## What the vision should say, and does not yet

The AI Factory's scope already includes an LLM sandbox with safety filters and logging, an
evidence and audit infrastructure, a model registry, data provenance, secure enclaves,
co-creation environments and a portability toolkit. What it does not say, and what the blocks
design should:

1. **Every action an agent takes is a recorded, attributed event.** Not every run: every tool
   call, through every block, with the identity it acted for. That is one sentence, it is what
   the AI Act, NIS2 and ISO 27001 each ask for in their own words, and the recording seam is
   where it is enforced. Say it as the design's first rule.
2. **Classification decides the tier.** A use case carries a confidentiality, integrity and
   availability level; the level selects the isolation tier, the logging depth, the retention
   and whether transcripts are stored at all. The agent does not choose. The healthcare use cases
   ask for exactly this and nothing in the current picture holds it.
3. **An agent acts as a person, never as a service.** Delegated, scoped, expiring credentials
   from the federation are the difference between an agent platform and a shared service
   account with a chat interface. This is the one item that blocks every SURF-run agent, and
   it is not in any plan.
4. **Approval is a record, not a prompt.** A write to a repository, a job submission, a message
   sent for someone: the yes is stored beside the run, with who gave it. Human oversight under
   the AI Act is this, and NIS2's evidence is this.
5. **Evidence is a by-product.** The run record, the provenance documents, the SBOMs and the
   attestations are produced by running the work. Nobody assembles them for an audit. That is
   what "trustworthy AI as default" has to mean in engineering terms, and it is what this
   repository is for.
6. **Evaluation is a workload.** The machine's acceptance criteria name neither an agentic
   workload nor an evaluation workload. Both will run on it, and both have a cost model unlike training
   or inference.

The items in the "not built yet" cells above are the work these six sentences imply, in the
order the blocks page gives.
