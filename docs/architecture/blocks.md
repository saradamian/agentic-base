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

The first list had six. Checking it against what SURF runs and what the AI Factory names as its
common denominators, identity and access, a data plane with object and POSIX tiers, accounting
and quota, a shared GPU pool, a common home for artifacts, uniform observability, and tenant
isolation, adds three and sharpens two.

| block | wraps | what exists today | status |
|---|---|---|---|
| **hpc** | Slurm on Snellius, LUMI and the AI Factory; a served model on it | agentic-env's slurm_companion, 51 tools, two curated profiles, an SSH backend; three separate slurmrestd clients in willma2, the AI4Science prototype and a stub in `python_slurm_wrapper` | the most duplicated capability at SURF and the one to consolidate, in its own package, once slurmrestd's availability is settled with the operators |
| **inference** | Willma, the AI Hub back office | an OpenAI-compatible endpoint and nothing published as a block; the model catalogue, serve requests and the Whisper transcription that Research Cloud items already call | a block, because every other block's agent needs a model and the catalogue is the thing to expose |
| **knowledge** | Confluence today; the SURF knowledge base and the education search portals tomorrow | agentic-env's confluence product, 20 tools, already served over MCP with a curated surface; a separate team is building an MCP server for edusources.nl | the cheapest first extraction, and the proof that two teams' MCP servers can share one catalogue |
| **software** | EasyBuild and EESSI | agentic-env's easybuild product, 10 tools, with a sandboxed validation backend | ready to extract |
| **data** | the object stores (Swift, LUMI-O, MinIO on the platform), the POSIX tiers, dCache, iRODS and Yoda, Research Drive, the AI Factory's dataset-as-a-service | the AI4Science prototype's dataset vocabulary; agentic-env's staging scripts for LUMI-O; nothing agent-facing | a block, and the largest gap: an agent that cannot find, stage or cite data does not do research |
| **artifacts** | the container registry, a model registry, dataset versions and checkpoints | GitLab and Harbor registries on the platform; MLflow named as the registry in the AI Factory design; content-addressed artifacts in agentic-env's lineage | missing. The GPT-NL interview asked for exactly this: a shared versioned store and a common registry |
| **identity** | SURFconext and SRAM: who you are, which project you belong to, what you may touch | every block needs it and none carries it; the platform's tenancy model | not a block an agent calls; the thing every block's surface is scoped by. Named so it is not forgotten |
| **accounting** | GPU-seconds, storage, and energy per tenant and per run | Slurm and EAR accounting on Snellius; the AI Factory asks for accounting "the same way however the work was launched"; the run record carries joules beside tokens | a small read-only block, and the one that answers the question a funder asks first |
| **runs** | the record and the referee | this repository's service and its four-tool server | exists |

Two of the nine are not agent tools at all. Identity is what scopes every surface, and
accounting is what the platform bills on; they appear because a design that leaves them implicit
gets them wrong, which the AI Factory memo says in its own words.

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

1. Extract the **knowledge** block first. Smallest, already over MCP, needs no scheduler
   decision, and proves the extraction loop and the template on something that cannot break a
   cluster.
2. Settle slurmrestd availability with the Snellius operators, then start the **hpc** block from
   the `python_slurm_wrapper` stub with willma2's token handling and the AI4Science schemas.
3. Define the **data** block's surface with the data teams before writing it; find, stage and
   cite are the three verbs an agent needs, and the systems behind them are theirs.
4. Leave **identity** and **accounting** as named constraints until a block needs them for real.
