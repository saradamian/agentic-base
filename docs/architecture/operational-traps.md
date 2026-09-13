# Operational traps carried over

Each of these cost time or results in the predecessor project. They are written down because
none of them is visible in code review, and several apply even though the code they came from is
not being ported.

## Cleanup that outruns the work

A disk reaper that removed any container older than 50 minutes ran against tasks with a two-hour
budget. It killed roughly a third of them under their own agents for almost three days. Worse,
each one was then recorded as a model failure instead of an infrastructure failure, so it never
appeared as missing data at all.

Derive any cleanup threshold from the runtime of the work it must outlive. Never write it as a
literal.

## Draining does not shorten a wall clock

The same shape appears in serving. Taking a replica out of routing stops new work arriving, but a
task dispatched just before that still dies when the replica's allocation ends. So the drain lead
has to be longer than the consumer's task timeout. That is why a lead of two hours is correct and
looks absurd to anyone who has not been bitten.

## A process identifier of zero

Zero is a sentinel in several APIs, and sending a signal to it signals the caller's own process
group. In our case it killed the controller doing the reaping. There was no traceback, because a
signal is not an exception, and the launching wrapper died in the same group, so the supervisor
logged a routine restart. Nobody looked for two and a half hours.

Guard every signal path on a positive identifier.

## Killing a process does not stop the work

A chain was stopped by killing four identified processes in dependency order, with a clean unwind
and a report that it had stopped. It had not. The actual driver was a grandchild, so killing its
parent reparented it to the session leader and it survived, ran for another forty minutes against
a serve that no longer existed, and wrote fifteen more results. Eleven were infrastructure
timeouts at a single step with no output. Booking them would have moved that arm's failure rate by
nine points, in the direction that supported the hypothesis.

Three properties, all of which the project's own stop script already had before this happened:

Identify orphans by their parent rather than by a remembered list of process identifiers, because
reparenting is what a kill produces and a remembered list cannot describe it.

Never let the matcher match itself.

Verify by the absence of the work rather than the absence of the processes you happened to know
about. No containers, no new rows. An absence you could not have contradicted is not evidence,
which is the same rule that makes an unplaceable record unplaceable rather than assumed.

The lesson is not that reparenting is subtle. It is that the tooling already knew and someone
hand-rolled around it.

## Searching for your own pattern

A process search by command line matches the shell running the search. This has killed working
sessions three separate times.

## Guards that cannot fail

One validity check reported clean for weeks while its per-arm dictionary was keyed off a leftover
variable and could hold only one entry. It was cited during those weeks as evidence the arms were
comparable.

Every guard needs a positive control, and the control needs to be confirmed failing.

## Defaults that fabricate a value

A memory-budget constant was used whenever a live scrape had not yet reported real numbers. On
unknown hardware, at startup, the system therefore invented a budget and admitted work against it.
A default that fills a gap with a plausible number fails open in the direction nobody checks.

## Simulation modes that cover reads

A dry-run flag that also stubs read operations returns a plausible cluster description, which
somebody will then size a deployment against. If reads are simulated, the returned data has to say
so.

## Absence read as evidence

A sweep that searches four login nodes and finds nothing means nothing if there are six. We lost
time to a week-old process on a node that was not in the list, resubmitting a finished study's
jobs after every cancellation. Report how much was examined next to the result.

## Running is not ready

A scheduled job in the running state proves a node was allocated. The model may still be loading,
or may have crashed already. Only a completed request through the real path licenses reporting an
endpoint as usable.

## A model answers to its serving name

That name is set at launch and is not the repository identifier. Get it wrong and every request
fails with a not-found while the pool looks healthy.

## Utilisation is the wrong metric

Driving concurrency up to keep the accelerators busy made a production run two and a half times
slower and produced nothing usable, with utilisation pinned at full throughout. Throughput is not
monotonic in concurrency. Optimise completed work per hour.

That is two operating points, not a tuning study. We never located the peak.

## Local databases on shared filesystems

Concurrent writers on a shared write-ahead log block inside the filesystem, and an asynchronous
process stops entirely. The symptom is an agent that is alive, an endpoint that is healthy and
idle, and sockets full of unread data. Anything holding a local database puts it on node-local
disk.

## Constants resolved at import time

Configuration layered after the import is silently ignored. Environment values for every limit
were dropped unless some other module happened to import the configuration first.
