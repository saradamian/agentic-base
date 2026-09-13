# Contributing

House rules, kept short so the next reader has less to hold in their head. Most exist because
something specific went wrong once; `docs/ENGINEERING.md` says what each one cost and which test
fails when it stops being true.

## Where the reasoning lives

Code is terse. A docstring states purpose and constraints, what a reader needs to use or change
the thing safely. It does not carry history, justification, or an argument that the change is
correct; that goes in the commit message and, when it is a decision, in `docs/decisions.md` or
`docs/architecture/`. A reader who wants to know *why* looks there.

## Two halves, one repository

The **library half** is what other projects import. It installs on Python 3.10 with pydantic,
pydantic-settings, httpx and PyYAML, and nothing else. Which modules are portable is a list in
`tests/test_portable_surface.py`, not a paragraph, and its guards fail when the list stops being
true. The **service half** is an optional extra. If your change makes a portable module import a
service dependency, the suite tells you.

## Values that belong somewhere else

Anything that is a fact about *where* this runs rather than *what* it does, a registry, a
hostname, a pull secret, an environment name, does not go in code, chart defaults or the
Dockerfile. It goes in a deployment overlay outside this repository, and the overlay may only
add files, never modify ours; `overlay.cfg` declares which paths it owns and a guard refuses a
change here that creates one. The Dockerfile takes registries as build arguments for this reason.
The pattern and its tool are in `docs/architecture/deployment-overlay.md`.

## Running the gate

```
uv sync --group dev --extra service --extra provenance
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src tests
.venv/bin/pytest tests -q
```

Run pytest **without** `-W ignore`. The repository treats warnings as errors on purpose, and a
run that suppresses them is a run that cannot fail on the class of defect the policy exists for.
Two real defects reached the public gate that way in one day. If a warning must be tolerated,
scope a `filterwarnings` entry to that one message, name the upstream cause, and say when it can
be removed.

Continuous integration runs the same five steps on 3.10 and 3.14. If your machine has only one,
the runner is the other. Two more checks are required to merge and do not run locally: a
dependency review of what the change adds, and an audit of the fully pinned set.

## What a public page may not carry

The repository is public. No hostname outside the short public list, no email address, no home
path, no private address, no reference to an internal document or wiki. `tests/test_public_hygiene.py`
checks by shape and says which line; a new public host is added to its list, and that addition
is a review decision. Numbers from the AI Factory's plan, task and deliverable names included,
are fine; its documents are not, and neither is anything quoted from them.

## Tests

One test per behaviour, at the highest seam that can actually fail. Name the behaviour and the
condition: `test_a_verdict_from_a_degraded_instrument_is_not_citable`, not `test_citable`. A test
that no plausible bug would fail should be deleted. A new module needs a test module of the same
name in the same change; a guard checks.

**Break every guard you add.** Before trusting a check, make the thing it checks wrong and watch
it go red. A guard that cannot fail is worse than none, because it gets cited.

## Commits and pull requests

Conventional commits: `type(scope): description`, with `feat`, `fix`, `test`, `refactor`,
`docs`, `chore`, `ci`, `perf`. The pre-commit hook enforces it; install it with
`pre-commit install --hook-type commit-msg`.

One behaviour per pull request. The description says what changes, what does not, and what is
deliberately left for later. It must not claim more than the diff delivers.

`main` accepts pull requests only, with the gate green on both interpreters, every review thread
resolved, and a linear history. Push everything before arming auto-merge: a commit pushed after
the checks pass reaches the branch and never reaches `main`. There is no required reviewer count while the repository has one
maintainer; the gate is the reviewer. That changes the day there is a second.

## Versioning and releases

Semantic versioning. The version is the git tag; nothing is edited to cut a release.

- `0.y.z` while the interface is settling. A minor bump may change the public interface, and it
  is stated in the notes when it does. The import name is `agentic_base`; it was `app` until
  `0.2.0`. The distribution name is `surf-agentic-base` since `0.3.0`, because `agentic-base` on
  PyPI belongs to an unrelated project and a pin against it would have installed theirs.
- Patch releases fix without changing an interface.
- Tag `vX.Y.Z` on `main`. The release workflow verifies the tag's signature against
  `.github/allowed_signers`, builds the distribution, refuses if the built version differs from
  the tag, checks the wheel imports on Python 3.10, attests it, publishes a GitHub release with
  generated notes, and publishes to PyPI by trusted publishing. No token is stored anywhere.
- One version per merge a consumer is waiting on. A local tag is never re-pointed after it has
  been announced; three releases in one day crossed with a push that way.
- `CITATION.cff` carries the version and the release date; update both in the same change that
  tags.

## Dependencies

Dependabot handles security alerts and the workflow actions. Renovate handles ordinary version
updates and lock-file maintenance. They are split so they never open the same pull request.
Actions are pinned by commit hash with the version in a trailing comment; bump both together.
