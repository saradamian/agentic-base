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
`ResultState.CORRUPT` are all the same decision. A probe whose failure returns zero manufactures a
plausible answer out of a measurement failure, and the caller cannot tell it from the real thing.

## D4: Report the denominator

Anything that scans, counts or checks reports how much it examined alongside the result, so a
zero reads as a zero and not as silence.

A scan that returns nothing because its filter matched nothing is indistinguishable from a scan
that returns nothing because there was nothing to find, unless it says how many things it looked
at.

## D5: Provenance is required at the point of recording

Optional provenance is never supplied. Not from laziness, but through the honest path of least
resistance when someone is trying to get one thing working.

So `tenant` and `code_revision` have no default, and an outcome cannot be recorded without naming
the scorer that produced it. In the project this came from, a corpus of 12,630 outcome rows ended
up with 6,842 attributed to a convenience checker, 5,788 with no scorer at all, and none
attributed to the authoritative one. A scorer cannot be assigned to a verdict afterwards.

## D6: A detector keys on the artifact, not on a description of it

A check that looks for a marker string will match any text that describes the marker, including
the system's own documentation of itself.

A detector for whether guidance had been injected into a prompt matched every prompt in both arms,
because the prompt teaches the model about the injected section and quotes its header inline. The
verdict was implausible enough to be investigated. A less surprising false positive would have
stood. This is a property of self-documenting systems, not a quirk of one prompt.

## D7: The learning half of this platform is empty on purpose

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
