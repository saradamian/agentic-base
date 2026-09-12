# Moving the shared primitives here, and having agentic-env import them

The direction is that this repository holds the shared primitives and `agentic-env` imports them,
not the reverse. That gives each primitive one home. It also corrects what I did when
seeding this repository, which was to rewrite eight modules that already existed, smaller and in
several cases worse.

Everything below was measured on 2026-09-11 by three sessions working separately, and where they
disagreed the measurement settles it, not the argument.

## What was reinvented

| here | lines | already existed as | lines |
|---|---|---|---|
| `mcp/server.py` | 199 | the whole `agentic/mcp` package | 2,343 |
| `domain/run_record.py` | 191 | `observability/run_trace.py` | 443 |
| `hpc/clusters.py` | 109 | `products/slurm_companion/config.py` | 184 |
| `security/netsec.py` | 101 | `security/netsec.py` | 219 |
| `llm/health.py` | 98 | `llm/health.py` | 239 |
| `code_policy/policy.py` | 97 | `sandbox/policy.py` | 184 |
| `hpc/job_result.py` | 86 | `core/job_result.py` | 111 |
| `limits.py` | 38 | `limits.py` | 175 |

Two more were described as new here and were not. The validity check is the campaign's missingness
script, and the epoch declarations are the boundary logic from the ladder deriver. Promoting a
script to a tested module is real work, but it is not invention and the write-up should not claim it.

## What is genuinely added, and must survive the move

Four things, all small, and three are rules rather than code.

Provenance required at the write path: tenant and code revision have no default, and an outcome
cannot be recorded without naming its scorer. Measured on 2026-09-11 across all 33 trace stores on
this workstation, 10,920 rows: 6,178 name a convenience checker, 4,742 name nothing, and **none name
the authoritative scorer**. An earlier version of this paragraph quoted 6,842 and 5,788 with no
denominator, and those do not reproduce against any store set. The zero is the robust part and it is
the part the requirement rests on; quote the other two only with the store count beside them.

The validity check as a library with a positive control confirmed to fail.

Epoch declarations, including on a component version, which is what the next section is about.

The hash chain over audit fields.

Two behaviour corrections also belong to this repository and not to relocation: the health probe
asserts a completed trivial completion rather than a non-5xx status, and limits resolve when read, not at import.

## Move order

Three sessions proposed three orders. Measured, there is no conflict: the candidate leaves all
have zero internal imports, and the tool-types module is the root of the *tool* subtree
specifically, not of the leaves.

**Start with `core/job_result.py`, and choose it for process risk rather than value.** It is
stdlib-only and already written to be portable, because its emitting half runs inside cluster jobs
where the package is not installed. That makes it the cheapest possible rehearsal of the
import-then-delete loop: if the loop has a flaw, it should surface on 148 lines that cannot break
anything, not on a module something depends on. The first move is chosen to de-risk the process.

**And `limits.py` should not move at all, only its mechanism.** The file holds 94 constants,
measured, among them `DECK_MAX_WORDS_PER_SLIDE`, `MEETING_RAID_MAX_TOKENS` and
`GITLAB_MR_CHANGES_PAGE_SIZE`. Those are `agentic-env` product policy, not base-layer primitives,
and a bottom layer carrying a slide word count has stopped being one. What is generic is the
mechanism: env-configurable, resolved when read rather than at import, one source of truth. Move
that; leave the constants at home. Otherwise the first thing a second consumer inherits is our
deck builder's opinions.

**Then the rest of the leaves.** `core/job_result.py`, `security/netsec.py`, `llm/health.py`,
`core/atomic_write.py`, `observability/conventions.py`, `core/container.py`, `core/slurm.py`. Each
has no internal imports, each is independently revertible, and none forces an interface decision.
The job-result protocol is already written to be portable, because its emitting half runs inside
cluster jobs where the package is not installed.

One candidate is **not** a leaf, against the table above. `sandbox/policy.py` imports
`..config.SandboxConfig`, so moving it drags a configuration module that belongs to the application,
not to this layer. It needs the dependency inverted first: the policy takes its limits as an
argument rather than reading a global. That is a behaviour-preserving change on their side, and it
has to land there before the move, not here afterwards.

**Second, `tools/types.py`.** 109 lines, no internal imports, and 45 files import it. It is the
root of everything tool-shaped, so the tool subtree cannot move before it.

**Third, the MCP protocol layer.** Bridge, client, transports and profiles are roughly 1,150 lines
whose deepest coupling is `tools.types`. They move once the second wave lands, and they replace the
hand-rolled server here, which lacks HTTP transport, keepalive, bearer auth, curated profiles, the
pre-flight check and the client for consuming external servers.

## What does not move

**The MCP pipeline.** It is the chokepoint that restores journalling, trace capture and injection
defence for calls that bypass a runtime, and it is the reason MCP-with-logging is worth having.
It is also the most coupled file in that package, reaching into a journal, a trace store, lineage,
an OpenTelemetry bridge and two security modules. So this layer declares the seam and the host
fills it: see `app/recording.py`. An application with nothing to record gets the no-op.

**The GSAR resolution inside limits.** It reads a file written by the self-improvement loop, which
makes it a hook into that loop wearing a constants module's clothes. The constants can move; that
resolution stays.

**`scaffold.py`.** Its rung set is experiment identity, not a primitive. A rung missing from it is
simultaneously dropped from every analysis table and exempted from the guard that every rung
declares every governed flag.

**The serve registry, as it stands.** A process identifier of zero there is a sentinel meaning the
ssh control master owns the forward, and signalling zero signals the caller's own process group.
Anything reusing it needs that guard and a cancel path, or it reproduces a two and a half hour
outage with no traceback.

**Skill generation.** Storage, retrieval and provenance are worth carrying. Generation is not: of
21 artifacts minted over months, one is in demonstrable use, two of three generators produced
nothing ever used, and nothing was ever promoted. The maintenance apparatus exists because the
generation produces duplicates.

**Cluster profile values.** The shape is reusable. The values are site-specific.

## Two conditions on the first import

**Relocation and behaviour change land separately.** Moving a module that behaves identically
changes nothing a corpus can observe. Changing what the health probe asserts does. Bundled, the
boundary becomes unattributable, which is the mistake the epoch constants exist to prevent.

**Record the resolved version of every component.** A configuration fingerprint governs flags and
cannot see the version of imported code, so once `agentic-env` imports from here, two runs can
share a fingerprint and a revision and still have run different software. `RunRecord` carries
`component_versions` for this, and `epochs` treats a record with no version for a named component
as unplaceable instead of guessing. Cheap now, unrecoverable later.

**And publishing it here does nothing unless the consumer reads it.** Verified on 2026-09-11:
`agentic-env`'s rung fingerprint digests flags, environment exports and budget, and no code version
of any kind; its environment capture records that package's own version through package metadata,
not a dependency's. Several of the modules moving first sit on the execution path, so a version
bump here would change behaviour while two cells continued to fingerprint identically, and their
ledger keys cells by fingerprint.

So this is a prerequisite on the consumer's side of the first import, not an improvement on ours.
Until their fingerprint reads the component version, we can publish it perfectly and they will
still record two different arms under one identity. It is worse than the in-repository version of
the same problem, because the code that changed is no longer in their history at all, so a
suspicious reader cannot reach it with `git log`.

One consequence for them to fix in the same change: that fingerprint's own docstring describes
itself as a digest of everything that defines a rung. That sentence stops being true on the day
the dependency lands.

## Before the first import

Re-check that no campaign is running, immediately before, not hours before. The reading that
says it is safe is a point in time, and the action that falsifies it is usually someone else's and
looks like progress.


## A protocol in the first wave

`core/slurm.py` carries `SlurmBackend`, and it is one of two protocols in the whole of
`agentic-env`. Both declare methods only, so neither will acquire the invariance defect on the way
down: a protocol whose members are declared as attributes reads as invariant, and a consumer's
frozen record then fails to satisfy the interface built to accept it. Both protocols in this
repository had exactly that defect and it was found by the first run of a type checker that had
never run.

The risk is not in what moves now. It arrives with the next protocol someone adds to a module that
has already moved, and this plan is the only place anyone will look for that.

## One challenge recorded rather than acted on

A peer's review argues that `tenant` should be demoted from required, on the grounds that
multi-user infrastructure for one and a half single-user consumers produces a required field
filled with the same constant string forever, which is a required field carrying no information.
That is the failure mode the scorer rule exists to prevent, one field over, and the parallel is
fair.

It is not being acted on, for one asymmetry that decides it, now written up as a general rule in
`docs/decisions.md` D9 so the next field does not need the same argument. **A tenant is
recoverable after the fact and a scorer is not.** You can always work out which project a run belonged to; you can never
work out which checker produced a verdict once the run is over. So the cost of getting `tenant`
wrong is an annoying backfill, while the cost of getting `label_source` wrong is a corpus that
cannot be cited. Requiredness is worth spending where the information is unrecoverable.

The second reason is weaker and should be stated as weaker: the declared destination is a
multitenant facility, so the constant string is expected to stop being constant. Arguments from a
future deployment are exactly the kind this repository is supposed to distrust, so it is the
asymmetry above that carries the decision, not this.
