# Security

## Supported versions

| version | supported |
|---|---|
| 0.8.x | yes |
| 0.7.x and earlier | no |

While the major version is `0`, only the latest minor receives fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:
<https://github.com/saradamian/agentic-base/security/advisories/new>. It reaches the maintainers
and nobody else. Do not open a public issue for a security problem.

You will get an acknowledgement within five working days, and a decision on whether it is
accepted within fifteen. If the report is of a vulnerability being actively exploited, say so in
the first line: that starts a 24-hour clock under the Cyber Resilience Act, and
`docs/architecture/incident-response.md` is what we follow. Accepted reports get a fix, a release,
and a credit in the advisory unless you ask otherwise.

## Scope

The service refuses by default. Every data route needs a bearer token from `API_TOKENS`, and a
token reaches only the tenants listed for it; another tenant's run looked up by id is not found
rather than forbidden. `AUTH=none` exists for local development and logs a warning. A way to read
or write a tenant's runs without a token that lists it is a vulnerability, and so is a way to
record a citable outcome through a token whose entry does not grant that scorer under
`label_sources`.

The library half fetches URLs on behalf of agents and filters generated code before it runs.
Both are documented as bounding accidental damage, not as boundaries against an adversary; see
the module docstrings in `src/agentic_base/security` and `src/agentic_base/code_policy`. A report
that one of them is escapable by a determined attacker is welcome and will be handled, but it is not a surprise.
Where an agent is untrusted, enforce outbound access in the network as well: an egress proxy, or
a network policy that allows only the destinations you intend.

## What checks run

- Dependabot: alerts and security updates for the Python set, version updates for the workflow
  actions.
- Renovate: ordinary version updates and weekly lock-file maintenance.
- `supply-chain` workflow: a dependency review on every pull request, refusing a new dependency
  with a known vulnerability of moderate severity or above, and a `pip-audit` of the fully pinned
  set, every extra included, on every push and pull request.
- The same workflow's `secrets` job scans every file and every commit with gitleaks, plus one rule
  of our own for a key in the shape a SURF service issues, which no provider rule matches. GitHub's
  generic, non-provider patterns are not available on this repository.
- All three `supply-chain` jobs are required checks, beside the gate on both interpreters and the
  `image` job, which builds the image and starts it.
- CodeQL on every push and pull request; secret scanning with push protection.
- OpenSSF Scorecard on every push to `main` and weekly, published to code scanning.
- Every release carries build provenance for the distribution files. From 0.4.0 it also carries
  an SBOM attestation, the SBOM taken from the wheel installed on the consumer floor, and PyPI
  receives the same files, each verified against its provenance before upload; for 0.3.4 and
  earlier only the files on the GitHub release verify. Check one with
  `gh attestation verify <file> --repo saradamian/agentic-base`.
- Workflow actions are pinned by commit hash with the version in a trailing comment.
- `tests/test_public_hygiene.py` on every change: no page or file may carry a link to a host
  outside the public list, an email address, a home path, a private address or a reference to an
  internal source. It works by shape, not by a list of the things it is meant to hide.

The image is built and started on every change, to prove it runs and carries no development
tools, but not published or scanned here: the deployment pipeline on the SURF Developer Platform
builds the image it deploys and scans it there.

## Personal data

The run record stores the transcript a model received. The service can redact it before it is
written. It is off by default. `REDACTION=patterns` removes credentials, contact details, bank
and card numbers, IP addresses and the Dutch citizen service number; `REDACTION=names` adds people
and places, from a model on Willma with GLiNER as the fallback, and refuses the write when neither
can run. Credentials and the other pattern findings are masked before any text is sent to the
model. `docs/architecture/redaction.md` has the modes, what each caught on a sample, and what each
costs. Every record carries the `redaction` field, naming the instrument, its mode and its
model, and the `classification` of the data the run touched. A
transcript with `none` and a personal classification is a finding, and personal or health data
on the community isolation tier is refused at the write. Redaction replaces what it finds; it
does not remove personal data from a prompt before a model sees it, which is the agent's side.
