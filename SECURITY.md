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
- `tests/test_public_hygiene.py` on every change: no page or file may carry a link to a host
  outside the public list, an email address, a home path, a private address or a reference to an
  internal source. It works by shape, not by a list of the things it is meant to hide.

What does not run here: a container image scan, because no image is built on GitHub. The
deployment pipeline on the SURF Developer Platform builds the image and scans it there.

## Personal data

The run record stores the transcript a model received. The service can redact it before it is
written, with Presidio, when `REDACTION=presidio` is set; it is off by default, and without a
language model it finds contact details, bank and card numbers and the Dutch citizen service
number but not names or places. `docs/architecture/redaction.md` has the modes, what each caught
on a sample, and what each costs. Every record carries the `redaction` field, naming the
instrument, its mode and its model, and the `classification` of the data the run touched. A
transcript with `none` and a personal classification is a finding, and personal or health data
on the community isolation tier is refused at the write. Redaction replaces what it finds; it
does not remove personal data from a prompt before a model sees it, which is the agent's side.
