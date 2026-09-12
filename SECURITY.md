# Security

## Supported versions

| version | supported |
|---|---|
| 0.3.x | yes |
| 0.2.x and earlier | no |

While the major version is `0`, only the latest minor receives fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:
<https://github.com/saradamian/agentic-base/security/advisories/new>. It reaches the maintainers
and nobody else. Do not open a public issue for a security problem.

You will get an acknowledgement within five working days, and a decision on whether it is
accepted within fifteen. Accepted reports get a fix, a release, and a credit in the advisory
unless you ask otherwise.

## Scope

The library half fetches URLs on behalf of agents and filters generated code before it runs.
Both are documented as bounding accidental damage, not as boundaries against an adversary; see
the module docstrings in `src/agentic_base/security` and `src/agentic_base/code_policy`. A report that one of them
is escapable by a determined attacker is welcome and will be handled, but it is not a surprise.

## What checks run

- Dependabot: alerts and security updates for the Python set, version updates for the workflow
  actions.
- Renovate: ordinary version updates and weekly lock-file maintenance.
- `supply-chain` workflow: a dependency review on every pull request, refusing a new dependency
  with a known vulnerability of moderate severity or above, and a `pip-audit` of the fully pinned
  set, every extra included, on every push and pull request. Both are required checks.
- CodeQL on every push and pull request; secret scanning with push protection.
- OpenSSF Scorecard on every push to `main` and weekly, published to code scanning.
- Every release carries build provenance and an SBOM attestation for the distribution files, the
  SBOM taken from the wheel installed on the consumer floor.
- Workflow actions are pinned by commit hash with the version in a trailing comment.

What does not run here: a container image scan, because no image is built on GitHub. The
deployment pipeline on the SURF Developer Platform builds the image and scans it there.

## Personal data

The run record stores the transcript a model received. Nothing in this repository detects or
removes personal data from it before it is written; a consumer that records prompts from people
is responsible for that today. The observer seam is where a redaction step would sit, and it is
an open design item, not a feature.
