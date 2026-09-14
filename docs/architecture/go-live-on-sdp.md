# Going live on the SURF Developer Platform

The software is public and released: GitHub is the repository, PyPI carries `surf-agentic-base`.
What is not live is the service on the platform. This page is the path there, read from the
platform's own onboarding documentation.

## What the deployment repository is

This repository plus SURF's private overlay, composed with `scripts/overlay.py` and kept current
by merging `main`. The overlay carries everything that says where the software runs: the pipeline
definition that includes the platform's pipeline component for Python applications, the Flux
and Kustomize manifests per environment, the Backstage catalogue entry, the owners file, the platform's
Renovate configuration, and this runbook's site-specific half. See `deployment-overlay.md` for
the contract and the commands.

Already true of the software side: it was built from the platform's FastAPI template, so the
layout, Dockerfile and Helm chart are the platform's; the chart's grace period is derived from
the request timeout, not a literal; registries are build arguments.

## What a person has to do

1. **Access.** A platform forge account through SURFconext, then a ticket to IS to activate it,
   then permission to create a project in the target group.
2. **Create the project.** Repository and group settings are GitOps through the platform's GitLab
   configuration repository, so this is a merge request there. Home: the group that owns the AI
   Factory work, not a personal namespace.
3. **Compose and push.** `overlay.py compose` against the released tag, then push to the new
   project. The overlay's `sync-upstream` job keeps it current afterwards and opens a merge
   request per sync.
4. **Request a tenant** through the developer portal's self-service form: a namespace, access,
   PostgreSQL and S3 object storage. The platform team reviews it.
5. **Accept the SURFconext invite** that comes with team membership; set up `kubectl` with the
   kubelogin plugin.
6. **Match the names.** `project_name`, `tenant_namespace` and `helm_release_name` in the
   overlay's pipeline read `surf-agentic-base` and `services-surf-agentic-base`. They must match
   the tenant that is granted.
7. **Point `database_url` at the tenant PostgreSQL** through the platform's secret management, in
   the Secret the chart's `envFromSecret` names. The chart runs `agentic-base-migrate` as a
   pre-install and pre-upgrade hook, and the service refuses to start against an older schema.
   SQLite is for local development only.
8. **Issue a token per writer** in `API_TOKENS`, through the same secret management, each mapped
   to the tenants that writer records for. Without it the service refuses every data request,
   which is the intended state of a deployment nobody has configured.
9. **Push, and let the pipeline deploy** to development first, then promote.

## What to settle before it is useful

**Where the execution plane lives.** The platform's Kubernetes is the right home for this
service: the API, the record store, the validity checks. Agent runs execute on batch-scheduled
HPC. So the service needs an authenticated path from a platform namespace to a Slurm cluster.
Four clients for that exist at SURF today and none is shared; the survey and the proposal are in
`blocks.md` under the hpc block. This is a conversation with the platform team and the cluster
owners, not a decision to make here.

**Secrets never reach a job script.** A user's model credential or object-store key must not be
interpolated into a submitted script or exported into a job environment on a shared filesystem.
The platform has a secret-management guide; the execution plane has to honour it. Settle it
before there is a service on top. The larger form of the same question is delegated credentials:
an agent acting for a person needs a token minted for that person and that session, and
`blocks.md` puts that design with SRAM before any SURF-run agent goes live.

**Redaction.** Set `REDACTION=names` before the tenant sees personal data. The primary
detector is a model on Willma: `REDACTION_LLM_URL`, `REDACTION_LLM_MODEL`, and the key through
the platform's secret management into `REDACTION_LLM_API_KEY`. The service's tenant needs a Willma
grant for that model; a key without one answers 403 and every write falls to the fallback. The
fallback is GLiNER: `gliner` and `torch` in the image, the model and its pinned revision in the
image too, so nothing is downloaded at start, and a GPU in the pod if one is available, because on
CPU a long transcript holds the write for tens of seconds. Put the site's cluster and service names
in `REDACTION_ALLOW_LIST` in the overlay, never in this repository. `redaction.md` has the
measurements and what happens when both detectors fail.

**Retention.** The library decides which transcripts are older than a policy and erases them
without breaking the chain; nothing runs it yet. The deployment needs a scheduled job that runs
the sweep, a tenant setting to read the policy from, and a decision on who is told what was
erased.

**What the tenant sets.** Every run carries the class of data it touched and the isolation tier
it ran under. Today the writer states both. On the platform the tenant's use case should set
them, so the service needs a place in the tenant configuration to read them from.

## What the platform enforces regardless

- Containers do not run as root; admission policy enforces it.
- Namespaces carry resource quotas, small by default.
- Dependency vulnerabilities are tracked and gated in the pipeline.
- Settings changed by hand outside GitOps are reverted.
