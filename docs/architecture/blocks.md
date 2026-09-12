# Blocks: the common capabilities SURF exposes to agents, and where each one lives

SURF intends to offer a set of common building blocks, tools and skills, that an agent can use,
internally and externally. This page says what a block is, which blocks the existing systems
imply, how a block composes with others and is adapted by a downstream, and where this
repository stops. It was checked on 2026-09-13 against the internal Confluence (the NL AI
Factory architecture, its high-level MLOps design, the design memo of July 2026, the user
interviews, the SURF Developer Platform overview, the AI-at-SURF product list) and against the
code that exists in agentic-env, willma2 and the AI4Science prototype.

## Three layers

| layer | what it is | who owns it |
|---|---|---|
| **contracts** | what every block stands on: the tool contract, the recording seam, the curated-surface mechanism, the security primitives, the span vocabulary, the run record and the referee. No block lives here | this repository |
| **blocks** | one per system. An MCP server, a Python client for code that does not want a model in the loop, and the skills that say how to use the system well. Each its own package, each with the owner of the system behind it | the system's team |
| **catalogue** | where a block is found. Backstage on the SURF Developer Platform internally, the MCP Registry externally; each block ships its own catalogue entry | the platform |

The reason the base is not a block, and no block is in the base: a block imports the contracts,
and a package that imports something must not also contain it. That is also why the scheduler
client is not here, whatever the temptation; `boundaries.md` says this repository must not
submit jobs, and a block that does belongs with the people who run the scheduler.

## The blocks the existing systems imply

The first list had six, and the second nine. Checking it against what SURF runs, what the AI Factory names as its
common denominators, identity and access, a data plane with object and POSIX tiers, accounting
and quota, a shared GPU pool, a common home for artifacts, uniform observability, and tenant
isolation, adds three and sharpens two.

| block | wraps | what exists today | status |
|---|---|---|---|
| **hpc** | Slurm on Snellius, LUMI and the AI Factory; a served model on it | agentic-env's slurm_companion, 51 tools, two curated profiles, an SSH backend; three separate slurmrestd clients in willma2, the AI4Science prototype and a stub in `python_slurm_wrapper` | the most duplicated capability at SURF and the one to consolidate, in its own package, once slurmrestd's availability is settled with the operators |
| **inference** | Willma, the AI Hub back office | an OpenAI-compatible endpoint and nothing published as a block; the model catalogue, serve requests and the Whisper transcription that Research Cloud items already call | a block, because every other block's agent needs a model and the catalogue is the thing to expose |
| **knowledge** | Confluence today; the SURF knowledge base and the education search portals tomorrow | agentic-env's confluence product, 20 tools, already served over MCP with a curated surface; a separate team is building an MCP server for edusources.nl | the cheapest first extraction, and the proof that two teams' MCP servers can share one catalogue |
| **stacks** | EasyBuild and EESSI: the software environments a job runs in | agentic-env's easybuild product, 10 tools, with a sandboxed validation backend | ready to extract. Named stacks, not software, because every reader who arrives asking about software development misreads the other name |
| **data** | the object stores (Swift, LUMI-O, MinIO on the platform), the POSIX tiers, dCache, iRODS and Yoda, Research Drive, the AI Factory's dataset-as-a-service | the AI4Science prototype's dataset vocabulary; agentic-env's staging scripts for LUMI-O; nothing agent-facing | a block, and the largest gap: an agent that cannot find, stage or cite data does not do research |
| **artifacts** | the container registry, a model registry, dataset versions and checkpoints | GitLab and Harbor registries on the platform; MLflow named as the registry in the AI Factory design; content-addressed artifacts in agentic-env's lineage | missing. The GPT-NL interview asked for exactly this: a shared versioned store and a common registry |
| **identity** | SURFconext and SRAM: who you are, which project you belong to, what you may touch | every block needs it and none carries it; the platform's tenancy model | not a block an agent calls; the thing every block's surface is scoped by. Named so it is not forgotten |
| **accounting** | GPU-seconds, storage, and energy per tenant and per run | Slurm and EAR accounting on Snellius; the AI Factory asks for accounting "the same way however the work was launched"; the run record carries joules beside tokens | a small read-only block, and the one that answers the question a funder asks first |
| **runs** | the record and the referee | this repository's service and its four-tool server | exists |

**Workflows are an artifact, not a run.** The platform's deliverables include packaging a
workflow, code, data pointers and an environment specification, as one thing that can be
exported, cloned and handed to a cloud with its lineage intact. A run record is the record of one
execution of such a package; the Process Run Crate is that record in a standard. The package
itself lives with the artifacts block, next to containers, datasets and model versions, and the
runs block references it. Nothing today produces one.

Two of the nine are not agent tools at all. Identity is what scopes every surface, and
accounting is what the platform bills on; they appear because a design that leaves them implicit
gets them wrong, which the AI Factory memo says in its own words.

## What the first list missed: the blocks for what an agent does

The nine above are what an agent reads and submits to. Checked against agentic-env's twelve
products, counting the external systems each one actually calls, and against the AI Factory's
service list, five capabilities used by most products appear in no block: the forge, sandboxed
execution, web egress, the channels people talk to an agent through, and the workspace a person
and an agent share. Without them no SURF-run agent can exist, whatever the other blocks offer.

| block | wraps | what agentic-env does today | why it is a block |
|---|---|---|---|
| **forge** | GitLab first, GitHub second: repositories, branches, merge requests, issues, discussion threads, pipelines and their failed-job logs | `gitlab_integration`'s client half, 753 call sites: issues, merge requests, diffs, threads with ids, replies and resolution, pipeline status, a shallow-clone branch workspace, with token redaction, encoded path segments, pagination and timeouts. `code_companion`, `matrix_bot` and `easybuild` read the forges too | a review companion, a triage bot and a coding agent are all this block plus a model. Ready to extract; the agent half (the review, the drift check's model stage, the companion) stays with the agents |
| **execution** | running agent-generated code with a declared isolation tier: a container with a read-only root and no bind mounts, or a microVM, on the platform | `code_companion`'s process sandbox, `swebench`'s Docker and Apptainer containers, `easybuild`'s validation sandbox, `pentest`'s subprocess tools; 63, 197 and 96 call sites. agentic-env's four-layer sandbox says in its own threat model that it is not a security boundary | nobody has said how agent-generated code runs safely on shared HPC with user namespaces disabled, and it is the first thing that breaks when a user runs an agent on the factory. Every product reinvents it. This is the block whose profile maps onto the platform's isolation tiers most directly. The base's structural filter is the pre-filter in front of it, never the boundary |
| **web** | outbound fetch and search with the SSRF check, an egress allow-list and a budget | `web_fetch` and `web_search` builtins, used by briefer, buca, deck_builder and the research agents | on a shared platform egress is a security decision, not a library call. One block, one policy, one place to log what an agent reached for |
| **channels** | how people reach an agent and it reaches them: Matrix, Microsoft 365 mail and calendar, meeting audio through Willma's transcription, later Teams | `matrix_bot` (100 call sites), `briefer` (Microsoft Graph, 61; Whisper through Willma, 21), Fred as the AI Hub's chat front | an agent that cannot be spoken to is a batch job. Internal services want the same front door |
| **workspace** | the place a person and an agent work on the same files: JupyterHub, code-server, a project's files and environment | agentic-env's branch workspace and sandbox-root handling; the platform's co-creation spaces are a stated deliverable with no system behind them yet | an agent working on someone's code needs the workspace the person sees. Missing |

Three more things cut across every block and are not blocks either. They are listed with
identity and accounting because leaving them implicit is how a platform ends up with a service
account that can do everything.

- **Delegated credentials.** An agent acting for a person acts with that person's rights, on
  GitLab, on Slurm, on the data stores, and no more. Today every product carries its own token
  in an environment variable, which is one identity for everyone who talks to it. The block
  surfaces need a token minted for the user and the session, scoped and expiring, which is
  SRAM's job to issue and every block's job to demand.
- **Triggers.** A service agent starts on an event: a merge request opened, a message in a room,
  a mail arriving, a schedule. agentic-env's runtime has schedule, file and user triggers and
  its GitLab product polls; the platform has webhooks. The trigger belongs to the control
  plane; the block only needs to name the events it emits.
- **Human approval.** A write to a repository, a job submission, a message sent on someone's
  behalf: each needs a place where a person can say yes, and a record that they did.
  agentic-env's supervisor gates this in-process; a SURF service needs it as a surface people
  see, and the run record is where the decision is kept.

## Could SURF run a code companion, or a GitLab companion, as a service?

Not yet, and the table says exactly why. Each row is a SURF-run agent; each cell is the block it
would stand on and whether that block exists as a package today.

| agent | inference | forge | execution | web | channels | knowledge | runs | delegated credentials |
|---|---|---|---|---|---|---|---|---|
| **GitLab companion**: reviews merge requests, triages issues, answers in threads | Willma, exists | needed, not a block | for running the tests it claims it ran; needed | optional | GitLab threads suffice at first | Confluence, exists over MCP | exists | required, not designed |
| **code companion**: edits a repository on request | Willma, exists | needed | needed, the whole point | docs lookups; needed | Matrix or the editor; exists in part | exists | exists | required |
| **research briefer**: reads mail, meetings and the wiki, writes a brief | Willma with Whisper, exists | no | no | needed | Microsoft 365 and Matrix; exists in part | exists | exists | required, per person |

So the GitLab companion is the nearest service: it needs the forge block, an execution block for
verification, and delegated credentials, and everything else it needs is already published or
in this repository. That is also the order to build in, because a review companion that cannot
run the tests it reviews is the assertion-versus-proof gap agentic-env spent a year closing, and
one that acts with a shared token is the security finding the platform audit would write first.

## The knowledge block, worked through

The first extraction, so the split is written down here and every later block follows it.

**Reuse.** The reference open-source server for Confluence and Jira over MCP is
`sooperset/mcp-atlassian` (MIT, maintained, Python 3.10). Its tool surface is a superset of
ours, and its configuration vocabulary, `CONFLUENCE_*` variables, a read-only mode, a tool
allow-list, space filtering, is what a user who has run it once expects. Under it sits
`atlassian-python-api` (Apache-2.0, maintained), the REST client for Cloud and Server. For
ingestion, `llama-index-readers-confluence` reads spaces and page trees on the same client. The
block adopts the client, ports the reference server's configuration vocabulary and tool
semantics so its documentation can point at theirs, and serves on this repository's SDK
transport. It does not import their server: it pins `mcp<2`, this repository is on 2.x, and the
two majors cannot share an environment.

**What the block keeps as contracts, with tests, because the reference server lacks them:**

1. host pinning on every page reference, so a page argument cannot become a request to another
   host carrying the wiki token;
2. token redaction on every error string, since MCP output lands in a chat window;
3. writes absent from the tool list unless enabled, not refused at call time, with separate read
   and write space allow-lists;
4. every read result carries id, space, version, last-modified and a clickable URL, because a
   model cannot cite what it was never given;
5. a pre-flight check that walks configuration, credentials, authentication, visible spaces and
   one live search, each failure naming the variable to change, exit 1 as a deployment gate.

**The split.** The block holds infrastructure: the client, the configuration, the five contracts,
the MCP surface recording through this repository's observer seam, the reader, the check. It is
publishable under this repository's standard. What reasons stays in agentic-env: the research
guidance skill, the verification stages the product declares (retrieval gate, provenance
citations, chain of verification, quality gate, confidence refusal), knowledge-store ingestion
with source confidence, TTL and tier promotion, agent mode, and the manifest that composes it.
After extraction the agentic-env product is a manifest that imports the block, declares its
stages and ships its skill.

**Before publishing:** the identifier sweep, since the deploy files and the wiki examples carry
site strings and a colleague's name has to be caught by hand; a fresh tree with none of
agentic-env's history; documentation written for a stranger's Confluence. Measured on the
current product, 1,687 lines, the only site-specific string in code is one image path in a
compose file, and its fourteen configuration variables carry no SURF value.

## What makes a block composable

- **It speaks MCP and nothing private.** Any agent, any framework, any vendor's client, connects
  to it. That is the entire composition mechanism, and the field settled it in 2025.
- **One tool name per capability across backends.** `submit_job` is the same name on Snellius,
  LUMI and the AI Factory, so telemetry aggregates and a skill written for one transfers to the
  others. Decision D1.
- **Surfaces are declared subsets with reasons.** agentic-env's profiles already do this:
  `hpc-ops` is read-only, `hpc-serve` adds serving, and the full surface stays in-process because
  a remote shell as the credential owner is not a thing to publish. Internal and external
  exposure are one block with a different profile and different authentication, never two
  codebases.
- **Every block records through the same seam and speaks the same span vocabulary.** A call
  through the knowledge block and a call through the hpc block land in one trace and one run
  record, which is what lets the referee judge what an agent did across blocks.
- **A block's profile maps onto the platform's isolation tier.** The AI Factory distinguishes a
  community tier, a virtualised tier and an isolated tier for sensitive data. A block published
  into the isolated tier exposes less, not the same surface behind a stricter login.

## What makes a block derivable

- **Site facts live in configuration, never in code.** Cluster profiles, registry hosts,
  endpoints, tenant names. The deployment-overlay contract enforces this for the base and applies
  to a block unchanged: a downstream takes the hpc block and overlays its own cluster profile.
- **Skills are files next to the block, in the open SKILL.md format**, with the anatomy
  agentic-env already requires: steps, the rationalisations table, red flags, a verification
  checklist. A skill for another cluster differs in the profile it names and nothing else.
- **A template repository derived from this one's standard.** The guards, the ledger, the release
  path, signed tags and attested wheels. A new block starts from the template and inherits the
  discipline without inheriting any code.

## What the internal documentation does not yet say

Nothing on the internal Confluence describes an agent-facing layer: no page on MCP, on skills, or
on agents as a workload, apart from one product line about an MCP server for the education
portals. The AI Factory's own architecture notes list train, fine-tune and infer as the three
verbs and have no box for an agent run, which is the gap the design memo of July 2026 calls the
common denominators without naming agents. This page is therefore the first written statement of
the layer, and it should move to Confluence once the block owners have read it.

## Order of work

0. Write down the **forge** block's surface with the GitLab team and the **execution** block's
   isolation contract with the platform team, because the first SURF-run agent needs both and
   neither is a library extraction; they are decisions.
1. Extract the **knowledge** block first. Smallest, already over MCP, needs no scheduler
   decision, and proves the extraction loop and the template on something that cannot break a
   cluster.
2. Settle slurmrestd availability with the Snellius operators, then start the **hpc** block from
   the `python_slurm_wrapper` stub with willma2's token handling and the AI4Science schemas.
3. Define the **data** block's surface with the data teams before writing it; find, stage and
   cite are the three verbs an agent needs, and the systems behind them are theirs.
4. Leave **identity** and **accounting** as named constraints until a block needs them for real,
   but design **delegated credentials** with SRAM before the forge block ships, since the first
   service agent cannot go live on a shared token.
