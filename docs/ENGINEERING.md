# The engineering standard

Why the rules in `CONTRIBUTING.md` are the rules. That file says what to do; this one says what
each rule cost to learn and, for every rule, which test fails when it stops being true.

The reason for the split is the standard's own first principle. Prose has no positive control: a
paragraph asserting a property stays comfortable while the property rots. So every section below
names its guard, and where there is none it says so rather than implying one.

## Where it comes from

Two repositories in the same group, mature on opposite axes. The numbers were counted, not recalled:

| | willma2 | agentic-env |
|---|---|---|
| merged through review | 490 merge requests | ~87 % of 1,823 commits went straight to trunk |
| test functions | 278 | 6,249 |
| coverage gate | none | ratcheted floor, enforced |
| conventional commits | 4.5 % | 95 %, hook-enforced |
| deploy, backup, rollback | yes | not applicable |

Neither is the model on its own. willma2 has the process and not the rigor; agentic-env has the
rigor and not the process. This repository takes both, and it could because it had no history to
migrate when the choice was made. That window closes once a repository has contributors and a
release, so the settings go in on the first day, not after the first incident.

## A guard that cannot fail is worse than none

It gets cited. Someone reads a green check as evidence, and the check was never able to go red.

Every guard here was broken on purpose and watched to fail before it was trusted, and that step
is part of adding one. The failures that taught it:

- A missingness check keyed its per-arm rates off a leftover loop variable, so the dictionary held
  one entry, the ratio was always 1.0, and it could not flag anything. It reported clean for weeks
  and was quoted as evidence the arms were comparable.
- A calibration reported a flawless result from a scorer that had never run, because the client was
  built without a model and every verdict was the fail-open default. It was caught only because the
  verdict type carried an explicit `degraded` flag.
- A boundary test's first repair was a skip on shallow clones, which fires on every run in
  continuous integration by construction, so the property would never have been checked where it
  mattered.

**Guard:** `tests/test_overlay_contract.py`, `tests/test_portable_surface.py` and
`tests/test_chart.py` each assert a rule and each was verified to fail when the rule is broken.
`tests/test_permitted_failures.py::test_an_unreadable_job_list_raises_instead_of_reporting_clean`
is the pattern in one name: a reader that could not ask must not report clean.

## A reader that could not ask must not report clean

Distinct from the above, and the more common shape. The instrument works; it just could not reach
the thing it was asked about, and it returns the same value as a genuine negative.

A documentation-drift gate whose model endpoint was unreachable produced 2,560 "uncertain"
verdicts, zero "stale", and exited 0. A permitted-to-fail flag turned that into silence, and a
wrong instruction merged behind the green pipeline. The exit contract now separates "nothing was
stale" from "nothing was checked", which is one extra exit code and the whole difference.

**Guard:** the deployment overlay's `doc-drift` job runs the tool once against an unreachable
endpoint and requires the "could not check" exit before trusting the real run. An older release
exits 0 there and the job fails, naming the reason. Upstream, `collection_ok` exists for the same
reason on the telemetry path.

## A permitted red is silence, not a warning

The pipeline verdict is what people read. A job allowed to fail, that fails, is indistinguishable
from one that passed unless someone opens the job list and then opens the job. Two gates in the
predecessor project were dead for a 165-commit consolidation behind a green pipeline, and two
separate sessions read that job list and moved past the red.

If a check cannot block, delete it or make it post something that reaches the verdict line.

**Guard:** `assert:no-permitted-failures` queries the *running pipeline's own job list* rather than
reading the pinned component's templates, because the component is renovate-bumped and a static
read describes only today's version. It is explicitly not permitted to fail, and it fails when it
cannot read the list.

## Derive a lead time, never write it as a literal

*A cleanup whose lead time is shorter than the work it must outlive destroys results silently.*
One invariant, three incidents, twice on batch infrastructure: a 180-second drain against
7,200-second work; a reaper with a stale 50-minute literal killing roughly a third of all cells for
66 hours with no log line; a 30-second container grace period against requests that run to 1,800.

The literal is not wrong when written. It drifts when the thing it was derived from changes, and
nothing connects them.

**Guard:** `tests/test_chart.py` asserts the grace period is computed from the request timeout plus
the pre-stop sleep plus a margin, and fails if a literal appears.

## Record provenance at the moment of the write

A field that can be filled in later will not be. Measured on our own corpus: 33 trace stores,
10,920 recorded outcomes, 4,742 naming no scorer at all and not one naming the authoritative one,
because attribution was a later step nobody ran.

So the creation model refuses a write it cannot attribute, and requiredness is spent where the
information is unrecoverable: a scorer cannot be reconstructed once a run is over, a tenant can.
`docs/decisions.md` D9 states the rule and the table of which side each field falls on.

**Guard:** `tests/domain/test_outcomes.py` asserts that recording an outcome without naming its
scorer is refused, and that a verdict from a degraded instrument is not citable however
authoritative its source.

## The ledger is held to the code

The reuse ledger says which concerns are adopted, bridged or built, and its own closing rule is
that an ADOPT verdict implemented by hand is a defect. For its first week nothing failed when
that happened, and it happened: the MCP surface hand-rolled the protocol while the ledger said
ADOPT.

**Guard:** `tests/test_reuse_ledger.py` parses every table in the ledger, reports how many rows
each check read, and fails when a module has no verdict, a BUILD row has no revisit condition, an
ADOPT module still carries the signature of doing the thing by hand, or an adopted vocabulary is
restated instead of imported. It was verified red on the hand-rolled server before that server
was replaced.

## Site facts live in escaped configuration

Anything that describes *where* software runs rather than *what* it does belongs outside the
artifact: a registry, a hostname, a pull secret, an environment name, a catalogue entry. A chart
that names one site's registry as its default is a chart that discloses a deployment topology and
cannot be reused.

A deployment repository is this repository plus an additive overlay, kept current by merging.
`docs/architecture/deployment-overlay.md` has the pattern and the alternatives considered.

**Guard:** `overlay.cfg` declares the paths an overlay owns and `tests/test_overlay_contract.py`
refuses a change here that creates one. The registries in the Dockerfile are build arguments.

## The library half must be importable by the people who will delete their copy

This layer exists so other projects can delete their copies and import instead. That only works if
they can import it. On the day this was checked they could not: the package declared Python 3.14
against a consumer whose floor is 3.10, and its core dependencies were a web framework, a migration
tool and a database driver, so importing a URL-safety helper would have pulled all three into a
container on a compute node.

Rules travel, storage does not. The outcome rules are functions over a structural protocol, so a
consumer keeps its own record type and still gets them.

**Guard:** `tests/test_portable_surface.py` lists the portable modules and checks that each parses
under the consumer's grammar, uses no runtime name newer than its floor, and loads no service
dependency when imported — the last in a fresh interpreter, because in-process it would pass
whenever an earlier test had already imported the database layer. It also checks the linter's
target version, which had been set to demand exactly the syntax the consumer cannot run.

## Run the suite under the policy the repository declares

This one has no guard, and that is a gap rather than an omission.

`pyproject.toml` makes warnings errors. Every local run on one day suppressed them and reported 271
passing; under the declared policy the suite could not collect at all. Two real defects were found
by the public gate instead, and six red pushes followed. A check run under a weaker regime than the
one declared cannot fail on the class of defect that regime exists for.

Continuous integration runs the suite on both ends of the supported range precisely because a
developer machine usually has one of them.

## A push after auto-merge is armed is a push to nowhere

Auto-merge fires the moment the required checks pass. A commit pushed to the branch after that,
an amend, a fix-up, a wording change, reaches the branch and never reaches `main`: the squash
already happened and the pull request is closed. It happened twice in one day on this repository,
and both times a consumer's tests, not ours, found the missing commit. Push everything, then arm;
or after a late push, read the pull request's state back before believing anything landed.

There is no guard for this, because the thing that would fail is a check that did not run.

## Signed history depends on the merge method, not on the author

Measured here on 2026-09-12. Commits authored and signed locally arrived on the trunk unsigned,
because rebase merge replays each commit as a new object and does not sign what it replays; the
author's signature cannot survive a changed parent. The same repository, squash merge, produces a
verified commit.

So the guarantee lives in the repository settings: rebase was removed from the allowed merge
methods. A rule that can be bypassed by choosing the other button is not a rule.

One caveat, because the green tick invites a stronger reading than it earns: a squash-merged
commit is signed by the forge, not by the author. It attests that the forge performed the merge,
not who wrote the content.

**Guard:** the branch ruleset permits squash only, with no bypass actors.

## Settings that are free on the first day

From willma2, which merged 490 requests this way: rebase merge, squash always, pipeline must pass,
discussions resolved, source branch removed, protected trunk. Here they are a branch ruleset
requiring pull requests, both interpreter checks strict, linear history, resolved threads, no
force-push, no deletion and no bypass actors, plus a tag ruleset making releases immutable.

Required approvals are zero, deliberately, while there is one maintainer: a person cannot approve
their own pull request, and a rule that blocks everything gets bypassed. The gate is the reviewer
until there is a second person.

The argument is not tidiness. Agent-assisted development multiplies whatever process exists, and
for a layer other projects depend on, unreviewed throughput is a different risk class than it is
for a single-consumer service.

## What not to copy

**Do not treat a large accreted context file as a specification for a new repository.** The one in
the predecessor project runs past two thousand lines, has carried several claims that were false on
arrival, and a fresh reader takes one project's compromises for requirements. Encode the same
knowledge as executable tests instead: `tests/lessons/` holds measured failures as tests that fail
if the lesson stops holding.

**Do not carry a subsystem across on the strength of its description.** The skill-generation loop
was measured before being dropped: 21 artifacts minted, one in demonstrable use, two of three
generators never produced anything used, and nothing minted ever cleared promotion. `docs/decisions.md`
D7 records the decision with the numbers, so it cannot be reopened with "you never measured it".
