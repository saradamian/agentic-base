# Security

## Supported versions

| version | supported |
|---|---|
| 0.1.x | yes |

While the major version is `0`, only the latest minor receives fixes.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:
<https://github.com/saradamian/agentic-base/security/advisories/new>. It reaches the maintainers
and nobody else. Do not open a public issue for a security problem.

You will get an acknowledgement within five working days, and a decision on whether it is
accepted within fifteen. Accepted reports get a fix, a release, and a credit in the advisory
unless you ask otherwise.

## Scope worth knowing

The library half fetches URLs on behalf of agents and filters generated code before it runs.
Both are documented as bounding accidental damage, not as boundaries against an adversary; see
the module docstrings in `src/app/security` and `src/app/code_policy`. A report that one of them
is escapable by a determined attacker is welcome and will be handled, but it is not a surprise.
