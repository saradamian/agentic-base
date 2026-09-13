# Moving shared primitives here, and having agentic-env import them

The direction is that this repository holds the shared primitives and `agentic-env` imports
them, not the reverse. That gives each primitive one home. It also corrects how this repository
was seeded: eight modules that already existed in agentic-env were rewritten here, smaller and
in several cases worse, before anyone measured. The measurements below were taken by three
sessions working separately, and where they disagreed the measurement settled it.

## What was rewritten, and what was added

| here | already existed as | what happened |
|---|---|---|
| `mcp/server.py` | the whole `agentic/mcp` package | both now sit on the official SDK; ours keeps the four tools and the pure dispatch |
| `domain/run_record.py` | `observability/run_trace.py` | ours is the record with the write-path rule; theirs stays the transcript store |
| `hpc/clusters.py` | `products/slurm_companion/config.py` | the shape is here, the values are theirs |
| `security/netsec.py` | `security/netsec.py` | here, with DNS pinning |
| `llm/health.py` | `llm/health.py` | here, asserting a completion rather than a status code |
| `code_policy/policy.py` | `sandbox/policy.py` | the structural pre-filter is here; their sandbox reads limits from a configuration module that belongs to the application, so the dependency has to be inverted there before it can follow |
| `hpc/job_result.py` | `core/job_result.py` | imported by agentic-env; the markers are parameters |
| `limits.py` | `limits.py` | the mechanism is here, the ninety-odd constants stayed |

Two things described as new here were not: the validity check is the campaign's missingness
script, and the epoch declarations are the boundary logic from the ladder deriver. Promoting a
script to a tested module is real work, but it is not invention.

What is added, and must survive any move: provenance required at the write path (measured on
33 trace stores and 10,920 rows on this workstation, 4,742 naming no scorer and none naming the
authoritative one); the validity check as a library with a positive control confirmed to fail;
epoch declarations, including on a component version; the hash chain over audit fields; and
the fields the cross-cutting capabilities write.

## The loop, as it runs

Each move is an agentic-env merge request that imports from here and deletes the copy, with the
pin on a minor range. The order was chosen for process risk rather than value: the job-result
protocol went first because it is stdlib-only, portable by construction, and cannot break a
cluster, so a flaw in the loop would surface on a hundred lines rather than on a module
something depends on. The span vocabulary, the provenance emitters and the MCP transport
followed, each as its own merge request. `from-agentic-env.md` says what each one found.

**`limits.py` moves as a mechanism, never as a file.** It holds product policy, slide word
counts and page sizes among it. What is generic is env-configurable values resolved when read,
one source of truth; the constants stay at home, or the first thing a second consumer inherits
is a deck builder's opinions.

**`sandbox/policy.py` is not a leaf.** It imports the application's configuration module, so
moving it drags that module along. The policy has to take its limits as an argument first, a
behaviour-preserving change on their side, before the move.

## Two conditions on every move

**Relocation and behaviour change land separately.** Moving a module that behaves identically
changes nothing a corpus can observe. Changing what the health probe asserts does. Bundled, the
boundary becomes unattributable, which is what the epoch constants exist to prevent.

**The consumer records the resolved version of every component.** A configuration fingerprint
governs flags and cannot see the version of imported code, so once `agentic-env` imports from
here, two runs can share a fingerprint and a revision and still have run different software.
`RunRecord` carries `component_versions`; `epochs` treats a record with no version for a named
component as unplaceable instead of guessing. agentic-env writes the installed version beside
every fingerprint, never inside it, declares which versions are equivalent, and its ledger
reader refuses to pool across a version no declaration names. Folding the version into the
fingerprint was tried and reversed: it re-keyed every existing cell.

Publishing a version here does nothing unless the consumer reads it, and the code that changed
is no longer in the consumer's history, so a suspicious reader cannot reach it with `git log`.
That is why this is a condition on the consumer's side of the import, not an improvement on
ours.

Re-check that no campaign is running immediately before a move lands. The reading that says it
is safe is a point in time, and the action that falsifies it is usually someone else's.

## What does not move

**The MCP pipeline.** It is the chokepoint that restores journalling, trace capture and
injection defence for calls that bypass a runtime, and it reaches into a journal, a trace store,
lineage, an OpenTelemetry bridge and two security modules. This layer declares the seam and the
host fills it: `agentic_base/recording.py`. An application with nothing to record gets the
no-op.

**The GSAR resolution inside limits.** It reads a file written by the self-improvement loop, a
hook into that loop wearing a constants module's clothes.

**`scaffold.py`.** Its rung set is experiment identity, not a primitive. A rung missing from it
is dropped from every analysis table and exempted from the guard that every rung declares every
governed flag, at the same time.

**The serve registry, as it stands.** A process identifier of zero there is a sentinel meaning
the ssh control master owns the forward, and signalling zero signals the caller's own process
group. Anything reusing it needs that guard and a cancel path.

**Skill generation.** Storage, retrieval and provenance are worth carrying. Generation is not:
of 21 artifacts minted over months, one is in demonstrable use, two of three generators produced
nothing ever used, and nothing was ever promoted. `decisions.md` D7.

**Cluster profile values.** The shape is reusable. The values are site-specific.

**Anything that is a block.** A scheduler client, a forge client, an execution backend. Those
are their owners' packages, importing this; `decisions.md` D10.

## A protocol in the first wave

`core/slurm.py` carries `SlurmBackend`, one of two protocols in the whole of `agentic-env`. Both
declare methods only, so neither acquires the invariance defect on the way down: a protocol
whose members are declared as attributes reads as invariant, and a consumer's frozen record then
fails to satisfy the interface built to accept it. Both protocols in this repository had exactly
that defect, and the first run of a type checker found it. The risk is not in what moves now; it
arrives with the next protocol someone adds to a module that has already moved, and this is the
only place anyone will look for that.

## One challenge, recorded

A review argued that `tenant` should be demoted from required, because a required field that
holds the same constant string forever carries no information, which is the failure the scorer
rule exists to prevent, one field over. The parallel is fair and the conclusion is wrong, for one
asymmetry: a tenant is recoverable after the fact and a scorer is not. The cost of getting
`tenant` wrong is a backfill; the cost of getting `label_source` wrong is a corpus nobody may
cite. `decisions.md` D9 states it as the rule for every next field.
