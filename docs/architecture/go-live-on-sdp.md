# Going live on the SURF Developer Platform

**Current state: not live.** This is a local repository with no remote and nothing pushed. The
steps below are the platform's documented onboarding path, read from the platform documentation
rather than inferred.

## Already done in this repository

- Built from `sdp/templates/python-fastapi-template`, so the layout, Dockerfile, Helm chart and
  environment manifests are the golden path rather than our invention.
- `.gitlab-ci.yml` includes `sdp/components/pipelines/python-application`, which brings build,
  test, lint, container publish, SBOM and deploy.
- `catalog-info.yaml` registers a Component and an API in Backstage, with a TechDocs reference so
  this documentation publishes to the portal.
- `manifests/` carries Flux HelmRelease and Kustomize overlays for development, test, playground,
  staging and production.
- `renovate.json` for automated dependency updates.

## What a person has to do

1. **Prerequisites.** Access to the platform's forge, and permission to create a project in the target group.
   A new GitLab account needs a login through SURFconext first and then a ticket to IS to activate
   it.
2. **Create the repository in the right group.** Repository and group settings are managed in a
   GitOps fashion through the platform's GitLab configuration repository, so this is a merge
   request there, not a click in the UI. Follow the platform's "managing GitLab repositories"
   guide. Suggested home: the group that owns the AI Factory work rather than a personal namespace.
3. **Request a tenant.** Through the self-service form in the developer portal. A tenant creates
   the Kubernetes namespace and access, plus the optional resources this service needs:
   **PostgreSQL** and **S3 object storage**. The platform team reviews the request.
4. **Accept the SURFconext invite role** that arrives with team membership, then set up `kubectl`
   with the kubelogin plugin to reach the namespace.
5. **Set the pipeline inputs.** `project_name`, `tenant_namespace` and `helm_release_name` in
   `.gitlab-ci.yml` currently read `agentic-platform` / `services-agentic-platform`. They must match
   the tenant that is actually granted.
6. **Point `database_url` at the tenant PostgreSQL** through the platform's secret management, and
   add an Alembic migration step. The SQLite default is for local development only.
7. **Push, and let the pipeline deploy** to development first, then promote through the
   environments.

## Two things to settle before it is genuinely useful

**Where the execution plane lives.** The platform's Kubernetes is the right home for this
service — the API, the record store, the validity checks. It is *not* where agent runs execute.
Those run on batch-scheduled HPC. So the service needs an authenticated path from a platform
namespace to a Slurm cluster, and the shape of that path is the open architectural question:
Slurm REST with per-user tokens, a bridge service, or a broker. Two internal projects already do
some of this and should be evaluated before a third is written. This is a conversation with the
platform team and with the cluster owners, not a decision to make in a repository.

**Secrets never reach a job script.** A user's model credentials and object-store keys must not be
interpolated into a submitted script or exported into a job environment on a shared filesystem.
The platform has a secret-management guide; the execution plane has to honour it. This is worth
settling before there is a service on top, because it is cheap now and expensive later.

## What the platform will enforce whether we plan for it or not

- Containers do not run as root. Policy is enforced at admission.
- Namespaces carry resource quotas, and they are small by default.
- Dependency vulnerabilities are tracked and gated in the pipeline.
- Everything is code: settings changed by hand outside GitOps will be reverted.
