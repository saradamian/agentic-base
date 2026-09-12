# Repository process

Agent-assisted development multiplies whatever process is already there. Across two comparable
repositories in the same group, the one with an enforced merge policy took 490 merge requests and
no direct pushes to its trunk. The one without took 883 direct pushes, about 87 percent of its
trunk history, in five months.

For a component other projects depend on that is not a preference. It is also cheap, because all
of it is free before there is history to migrate.

## On GitHub, where development happens

These are repository rulesets, not files, so they are listed here and read back when in doubt.

- `main` takes pull requests only. Required checks: `check (3.10)` and `check (3.14)`, strict.
  Linear history. Review threads resolved. No force-push, no deletion, no bypass actors.
- Squash is the only merge method. Rebase merge was removed because it replays commits unsigned;
  see `ENGINEERING.md`.
- Tags matching `v*` cannot be moved or deleted.
- Required approvals are zero while there is one maintainer. A person cannot approve their own
  pull request, and a rule that blocks everything gets bypassed.
- Auto-merge is on. Push everything before arming it: a commit pushed after the checks pass
  reaches the branch and never reaches `main`.

## In the deployment repository on the SURF Developer Platform

Repository configuration there is Terraform in the platform's GitLab configuration repository,
so these are a merge request there. The platform's own defaults match what willma2 merged 490
requests under: squash always, pipeline must pass, discussions resolved, source branch removed,
protected trunk. Keep the merge method squash, for the same signature reason as above.

## Asserted by tests here

`tests/test_process.py` asserts these, and each assertion was confirmed to fail when its subject
is broken.

- No job may be permitted to fail. A permitted failure that fails is silence, because the
  pipeline verdict is what people read. A check that cannot block should be deleted.
- The coverage floor is a constant in a test as well as a flag. A flag can be lowered in the
  same change that breaks what it protected. Raise the constant when coverage rises; never lower
  it.
- Commit messages are checked at commit time. Between the two repositories above, conventional
  commit compliance was 95 percent with the hook and 4.5 percent without.
- The package ships its PEP 561 marker, and the release job fails if an installed copy lacks it.

`tests/test_reuse_ledger.py` holds the source tree to the reuse ledger: every module has a
verdict, every BUILD says when to revisit, and an ADOPT module must not carry the signature of
doing the adopted thing by hand.

## Two things a deployment gets that the predecessor could not

A namespace per merge request, so review is opening the endpoint instead of reading the diff.

Deployment through GitOps from the first day. In the predecessor project a serve was submitted
from a temporary file and nothing recorded what a replica was, so a file format had to be
invented afterwards. On a cluster the manifest is the record.

## Provenance stops being best-effort

The predecessor snapshotted the commit, interpreter, endpoint and weight precision because it
could not pin any of them. With an immutable image digest the environment is pinned by
construction. Record the image digest, the configuration hash and the model digest as the identity
of a run; with the attested wheel and a signed tag, the reproducibility claim is checkable rather
than asserted.
