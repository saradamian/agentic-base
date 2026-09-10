# Repository process

Agent-assisted development multiplies whatever process is already there. Measured across two
comparable repositories in the same group: the one with an enforced merge policy took 490 merge
requests and effectively no direct pushes to its trunk. The one without took 883 direct pushes,
about 87 percent of its trunk history, in five months.

For a component other tenants depend on, that is not a preference. It is also the cheapest thing
on this page, because all of it is free before there is any history to migrate.

## Settings that are not in this repository

Repository configuration is Terraform in `the internal developer platform/gitlab-config`, so these are a merge
request there rather than a checkbox here. Apply all six when the repository is created.

- `merge_method = rebase_merge`
- `squash_option = always`
- `only_allow_merge_if_pipeline_succeeds = true`
- `only_allow_merge_if_all_discussions_are_resolved = true`
- `remove_source_branch_after_merge = true`
- protected trunk from the first commit

## Settings that are in this repository, and are asserted

`tests/test_process.py` asserts three of these, and each assertion has been confirmed to fail when
its subject is broken.

**No job may be permitted to fail.** A permitted failure that fails is silence, not a warning,
because the pipeline verdict is what people read. Two gates in the predecessor project were dead
behind a green pipeline through a 165-commit consolidation. A check that cannot block should be
deleted.

**The coverage floor is a constant in a test, as well as a flag.** A flag can be lowered in the
same change that breaks what it protected. Raise the constant when coverage rises. Never lower it.

**Commit messages are checked at commit time.** Between the two repositories above, conventional
commit compliance was 95 percent with the hook and 4.5 percent without. The difference is the
hook, and it is what keeps a changelog and a bisect usable when an agent commits frequently.

## Two more worth adding, neither of which the predecessor could have

A namespace per merge request, so review is opening the endpoint instead of reading the diff.

Deployment through GitOps from the first day. In the predecessor project a serve was submitted
from a temporary file and nothing recorded what a replica actually was, so a file format had to be
invented afterwards to answer the question. On a cluster the manifest is the record and it is
reconciled continuously.

## Provenance stops being best-effort

The predecessor snapshotted the commit, interpreter, endpoint and weight precision because it
could not pin any of them. With an immutable image digest the environment is pinned by
construction. Record the image digest, the configuration hash and the model digest as the identity
of a run, and add signing and an SBOM, and the reproducibility claim becomes auditable instead of
asserted.
