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
cannot be recorded without naming its scorer. The corpus that motivated it has 6,842 rows naming a
convenience checker, 5,788 naming nothing, and none naming the authoritative scorer.

The validity check as a library with a positive control confirmed to fail.

Epoch declarations, including on a component version, which is what the next section is about.

The hash chain over audit fields.

Two behaviour corrections also belong to this repository and not to relocation: the health probe
asserts a completed trivial completion rather than a non-5xx status, and limits resolve when read, not at import.

## Move order

Three sessions proposed three orders. Measured, there is no conflict: the candidate leaves all
have zero internal imports, and the tool-types module is the root of the *tool* subtree
specifically, not of the leaves.

**First, the leaves.** `core/job_result.py`, `security/netsec.py`, `llm/health.py`,
`core/atomic_write.py`, `observability/conventions.py`, `core/container.py`, `core/slurm.py`. Each
has no internal imports, each is independently revertible, and none forces an interface decision.
The job-result protocol is already written to be portable, because its emitting half runs inside
cluster jobs where the package is not installed.

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
