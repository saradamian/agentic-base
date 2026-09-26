# Decisions

Short records of choices that are cheap to make now and expensive to reverse. Each one is here
because getting it wrong in a previous project cost something specific.

## D1: Identical capability, identical tool name

When two backends implement the same capability, they register the same tool name. A filesystem
on a host and a filesystem inside a container both expose `read_file`, not `read_file` and
`docker_read_file`.

The reason is telemetry. Aggregating by tool name across backends only works if the names match,
and once two names exist for one capability every downstream count needs a translation table that
nobody maintains. There is no agent in this repository yet, so there is nothing to enforce and no
test to write. A test with one backend would be a guard that cannot fail, which is the first
thing this project is supposed to avoid. The sentence is the artifact.

## D2: Pass resolved configuration, never a name to resolve again

A component that receives the name of a configuration and looks it up downstream will resolve it
differently from the caller, and nothing will look inconsistent anywhere you can read.

In the predecessor project an experimental arm labelled as having a behaviour disabled ran with it
enabled for an entire era, because the caller passed a preset's name and the component below
re-resolved that name to the stock preset. One published contrast was invalidated. Pass the
resolved object.

This matters more on a platform with layered environment variables, mounted configuration and a
template someone else wrote, because there the same name resolves differently by design.

## D3: Three-valued outcomes, never collapsed

Anything that reports a determination reports yes, no, or could-not-determine. The third value is
never folded into either of the others.

`ValidityReport.could_have_flagged`, `ChainVerdict.could_have_failed`, `Epoch.UNKNOWN` and
`ResultState.CORRUPT` are all the same decision, and so is the service answering 503 when no
redaction detector could run instead of writing the transcript as if one had. A probe whose failure returns zero manufactures a
plausible answer out of a measurement failure, and the caller cannot tell it from the real thing.

## D4: Report the denominator

Anything that scans, counts or checks reports how much it examined alongside the result, so a
zero reads as a zero and not as silence.

A scan that returns nothing because its filter matched nothing is indistinguishable from a scan
that returns nothing because there was nothing to find, unless it says how many things it looked
at. `ValidityReport` counts the arms, channels and observations it read; a retention sweep says
how many records it examined; `extra.redaction` counts the strings each detector handled.

## D5: Provenance is required at the point of recording

Optional provenance is never supplied. Not from laziness, but through the honest path of least
resistance when someone is trying to get one thing working.

So `tenant` and `code_revision` have no default, and an outcome cannot be recorded without naming
the scorer that produced it. In the project this came from, 33 trace stores held 10,920 recorded
outcomes: 6,178 attributed to a convenience checker, 4,742 with no scorer at all, and none
attributed to the authoritative one. A scorer cannot be assigned to a verdict afterwards.

## D6: A detector keys on the artifact, not on a description of it

A check that looks for a marker string will match any text that describes the marker, including
the system's own documentation of itself.

A detector for whether guidance had been injected into a prompt matched every prompt in both arms,
because the prompt teaches the model about the injected section and quotes its header inline. The
verdict was implausible enough to be investigated. A less surprising false positive would have
stood. This is a property of self-documenting systems, not a quirk of one prompt.

## D7: No memory, skill or experience subsystem

There is no memory, skill or experience subsystem here, and the reason is not that it does not
matter.

In the predecessor project those subsystems were measured. A tree search ran with its evaluator
defaulting to off for an entire campaign, so it was not searching. A retrieval layer normalised
similarity by the length of the entry, so thorough entries could not be retrieved at all while
thin duplicates could. When the injection mechanism was finally measured properly it moved
outcomes in both directions, with identifiable causes on both sides, so the honest finding is that
the mechanism is real and its sign depends on whether the content fits the task's cost structure.

The conclusion carried here is that the mechanism is worth having and the content is something
each domain measures for itself. This platform records experience so that a future learning claim
can be tested. Filling this section with an unmeasured subsystem to avoid an empty one is the
mistake that produced the campaign above.

## D8: The library half is importable by its consumers, and that fixes its floor and its dependencies

This repository is two things. A service that runs on the platform, and a library that other
people import. The second is the whole point of the layer: code is supposed to leave `agentic-env`
and land here, which only works if `agentic-env` can import what lands.

On the day this was checked, it could not. The package declared Python 3.14 against a consumer
whose floor is 3.10, so the import would have failed outright on the workstation where its cells
run. Its core dependencies were a web framework, a migration tool, a Prometheus instrumentor and a
Postgres driver, so importing a URL-safety helper would have pulled all four into a benchmark cell
inside a task container with no route to a database. Neither problem was visible from inside this
repository, because everything here is the service.

So the split is explicit. The library half takes pydantic, pydantic-settings, httpx and PyYAML,
and nothing else. The service half is an optional extra. The declared floor is the consumer's
floor, not ours.

Two consequences worth stating, because they are the parts that get undone later.

The rules are functions over a structural protocol, not methods on our table. A consumer keeps its
own record type and still gets `is_citable`, `is_excluded` and `exclusion_channel`. If applying the
discipline required adopting the storage, the discipline would not travel, and a base layer whose
contribution does not travel is a second copy of the thing it meant to replace.

And the portable surface is a list in `tests/test_portable_surface.py` rather than a paragraph in
a document. It checks that every portable module parses under the consumer's grammar, uses no
runtime name newer than the floor, and loads no service dependency when imported, that the
declared floor still admits the consumer, and that the linter targets that floor.
The import check runs in a fresh interpreter on purpose: in-process it would pass whenever an
earlier test had already imported SQLModel, which is an absence the check could not have
contradicted. Each of the five was verified to fail when broken.

## D9: Spend requiredness where the information is unrecoverable

A field is required here when losing it cannot be repaired later, and optional when it can. That
is the whole rule, and it decides cases that would otherwise be argued one at a time.

| field | recoverable after the fact? | required |
|---|---|---|
| `label_source` | no. Once a run is over, nothing says which checker produced its verdict | yes |
| `code_revision` | no. A deployed tree may have no `.git`, and the record outlives the checkout | yes |
| `component_versions` | no. A fingerprint governs flags and cannot see an imported version | yes when one exists |
| `tenant` | yes. Reconstructible from model, paths and timestamps | no |
| `created_at` | yes. It has a default | no |

The rule arrived by disagreement, which is worth recording because it is why it is trusted. A
review argued that requiring `tenant` is multi-user infrastructure for one and a half single-user
consumers, and that the field would hold the same constant string forever: a required field
carrying no information, which is the failure the scorer rule exists to prevent, one field over.
The parallel is fair and the conclusion is still wrong, because the cost of being wrong about a
tenant is a backfill and the cost of being wrong about a scorer is a corpus nobody may cite.

A second argument was available and is deliberately not used: the declared destination is a
multitenant facility, so the constant string is expected to stop being constant. Arguments from a
future deployment are exactly the kind this repository is supposed to distrust. It is the
asymmetry above that carries the decision.

What this buys is that the next field does not need a debate. Ask whether the information can be
reconstructed from what will still exist. If it cannot, refuse the write without it.

## D10: No block lives in this repository

This repository is the contracts layer. The capability blocks an agent calls, hpc, inference,
knowledge, data, stacks, artifacts, forge, execution, web, channels, workspace, are each their
own package with the owner of the system behind them. They import this; nothing here imports them.

The rule exists because the alternative was tried. Eight modules were rewritten into this
repository from agentic-env in its first week, smaller and in some cases worse, and a scheduler
client was the next candidate. A base that contains a block cannot be imported by the block, the
block's owner has no repository to own, and the base grows until it is a second copy of the
thing it was meant to replace. The boundaries page (now archived, `archive/docs/architecture/boundaries.md`) said this repository must not
submit jobs; that is this decision applied to the first block.

## D11: A gap without a solution still gets a field

When an obligation has no implementation yet, the record gains the field the implementation
would write, with a default that keeps every existing writer working. `redaction` is `none`,
`principal` is empty, `classification` is unclassified, `approvals` is an empty list, and
`disclosure` and `content_marking` are `none`.

The alternative, adding the field when the solution arrives, loses the one thing a later reader
needs: which runs predate the solution. A corpus where every old row is indistinguishable from a
row the solution processed cannot be audited, and a solution with nowhere to write gets built
with its own store, one hop from the record it describes. D5 and D9 decide when a field is
required; this decides that it exists.
