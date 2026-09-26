# Archive

Pages that describe how this repository came to be, rather than how it works today. They are
kept for the record and are not maintained: links and claims in them are as they were on the
date they were archived. Nothing in `src/`, `tests/` or the documentation site depends on them.

Each file keeps its original path under `archive/`, so `archive/docs/architecture/x.md` was
`docs/architecture/x.md`. `git log --follow` on the archived path shows its full history.

| archived file | archived | why | where the live answer is |
| --- | --- | --- | --- |
| `docs/architecture/from-agentic-env.md` | 2026-09-26 | The account of the extraction from agentic-env; the extraction is done | `docs/architecture/reuse-ledger.md` for what is adopted, bridged or built |
| `docs/architecture/move-plan.md` | 2026-09-26 | The plan for moving shared primitives here; the moves it lists have landed or been dropped | agentic-env's `pyproject.toml` pins this package; the reuse ledger lists each module |
| `docs/architecture/kubernetes.md` | 2026-09-26 | What the predecessor's Slurm-era machinery becomes on Kubernetes; a one-time comparison | `docs/architecture/go-live-on-sdp.md` and the Helm chart in `charts/app/` |
| `docs/architecture/blocks.md` | 2026-09-26 | The design vision: twelve capability blocks, one per SURF system, and the order to build them. None of the blocks lives here, and none exists yet | the README for what exists; D10 in `docs/decisions.md` for why no block lives here |
| `docs/architecture/picture.md`, `picture.svg` | 2026-09-26 | The stack of blocks in one diagram | as above |
| `docs/architecture/layering.md` | 2026-09-26 | Where this layer sits under the blocks | as above |
| `docs/architecture/boundaries.md` | 2026-09-26 | The boundary against four neighbouring efforts, as what this repository must never do | D10 in `docs/decisions.md` |
| `docs/architecture/cross-cutting.md` | 2026-09-26 | Where logging, security, safety and compliance live across the blocks, and what the vision should say | `docs/architecture/compliance.md` for what the record produces today |
| `docs/architecture/operational-traps.md` | 2026-09-26 | Failures carried over from agentic-env's campaign operations; most concern code that is not here | the habit they share is in `START_HERE.md` |
| `docs/architecture/proposals.md` | 2026-09-26 | Two OpenTelemetry attributes to propose upstream; not filed | the reuse ledger's standards table |

To archive another page: `git mv` it here under its original path, drop it from `mkdocs.yml` and
`docs/index.md`, add a row above, and run
`pytest tests/test_doc_references.py tests/test_docs_site.py`.
