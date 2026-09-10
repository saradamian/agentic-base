# What Kubernetes changes

Most of the operational machinery in the predecessor project exists because Slurm has no service
model. On a cluster that whole class of work disappears, and rebuilding it would be the clearest
possible sign that nobody checked.

## Retired by the platform

| ours | why it existed | what replaces it |
|---|---|---|
| a readiness check distinguishing a scheduled job from a loaded model | Slurm has no readiness concept | a readiness probe. A pod does not join the service until it passes |
| SSH tunnels and a shared control socket | compute nodes are not routable | a Service and an Ingress |
| a registry of running serves that outlives the process | nothing tracked what was running | the API server is the registry |
| drain, rolling replacement, and a lead time before a wall clock | the allocation ends and takes the process with it | a rolling update and a disruption budget |
| a supervisor that restarts things | no supervisor existed | the restart policy |
| a check for daemons older than the code they run | long-lived processes held pre-fix code | immutable image digests and a rollout restart |
| disk guards, image pruning, cache eviction | one shared workstation disk | ephemeral storage limits and kubelet garbage collection |

Two lessons survive the move and are worth carrying explicitly.

The termination grace period has to exceed the longest in-flight request. Agent runs here take up
to half an hour, and the default of thirty seconds will cut a trajectory in half. This is the same
invariant as the drain lead: any cleanup whose timer is shorter than the work it must outlive
destroys results silently, and the loss is usually booked as a failure of the work rather than of
the cleanup.

The image pull that dominated our campaign is a solved problem in a cluster. A pull-through
registry cache removes it. We were bandwidth-bound at about two gigabytes per image over a twelve
megabyte per second link, and nobody should re-derive that.

## Do not rebuild the gateway

The cross-replica placement work has an upstream equivalent. The Endpoint Picker in the Gateway
API Inference Extension routes on queue depth, KV-cache utilisation, prefix-cache locality and
active adapter, which is the signal set we arrived at independently. Envoy AI Gateway, llm-d and
the vLLM production stack occupy the same space.

Arriving at the same signals independently is a point to cite in a conversation. It is not a
component to ship. Verify the feature set before quoting it, because this part of the stack moves
quickly.

## The one thing Kubernetes makes worse

The obvious autoscaler for inference is GPU utilisation, and that is precisely wrong.

Throughput is not monotonic in concurrency. Past a point the cache is oversubscribed, the engine
evicts in-flight requests and recomputes their prefill, and the accelerators stay pinned at full
while useful work falls. We measured 16,724 tokens per second with no preemptions at concurrency
18, against 7,024 with preemptions accumulating and per-call latency rising from about eleven
seconds to between sixty-four and eighty-two at concurrency 39.

An autoscaler reading utilisation sees the degraded state as healthy and scales the wrong way.
Scale on queued requests, and alert on the preemption counter.

Stated honestly, that is two operating points and not a tuning study. The peak was never located.

## What Kubernetes does not give you

Retries are not a defensible denominator. A workflow engine will re-run a failed step; it will not
tell you whether the resulting set of outcomes can be compared.

The hard part is the bookkeeping: what counts as done, what counts as an error, what has to be
voided and re-run, a timeout that must never be recorded as a result, retry caps, fingerprints so
two eras cannot be pooled, and the standing suspicion that exclusions correlate with the arm. None
of that comes from an orchestrator, and all of it has to sit on top. That bookkeeping is the part
of the predecessor project worth carrying. The scheduling underneath it is commodity.

## Sandboxing becomes real

The structural filter in `app.code_policy` is a pre-filter, and its own documentation says it is
not an isolation boundary. On Slurm with user namespaces disabled there was no boundary available
to put behind it.

On a cluster there is: a sandboxed runtime class, a read-only root filesystem, a seccomp profile,
no service account token, and a default-deny egress policy. This is the one place where a
limitation becomes an obligation.
