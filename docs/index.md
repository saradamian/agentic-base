# surf-agentic-base

The record and referee for agent runs, the security primitives an agent needs on a shared
platform, and the engineering standard that keeps both honest. The contracts layer under SURF's
capability blocks.

The [readme](include-readme.md) covers the service in a page. After that:

- [The picture](architecture/picture.md): the stack in one diagram, three ways
- [Blocks and layers](architecture/blocks.md): the design, what exists behind each block, and the order to build
- [Logging, security, safety and compliance](architecture/cross-cutting.md): where each lives, the obligations, what the vision should say
- [Decisions](decisions.md): the choices that are cheap now and expensive to reverse
- [Reuse ledger](architecture/reuse-ledger.md): what is adopted, bridged, or built, and why
- [The engineering standard](ENGINEERING.md): what each rule cost, and the test that enforces it
- [Repository process](architecture/process.md): the rulesets, and what the tests assert about the pipeline
- [Observability](OBSERVABILITY.md): what the service emits and where to point it
- [Compliance evidence](architecture/compliance.md): what the record produces for the AI Act and NIS2
- [Incident response](architecture/incident-response.md): the two clocks, who is told, and what this repository can hand you
- [Redaction](architecture/redaction.md): what removes personal data from a transcript, and what each mode catches and costs
- [Going live on SDP](architecture/go-live-on-sdp.md): the deployment repository and the open questions

The rest, in the order you are likely to want them:

- [Where this sits](architecture/layering.md) and [boundaries](architecture/boundaries.md): what this layer owns, and what it must never do
- [Operational traps](architecture/operational-traps.md): failures that are invisible in code review
- [The deployment overlay](architecture/deployment-overlay.md): how a deployment repository stays current without a fork
- [Proposals](architecture/proposals.md): the two attributes we carry as extensions and want upstream

Superseded pages (the extraction from agentic-env, the move plan, what Kubernetes changes) are
kept for the record in the repository's [archive](https://github.com/saradamian/agentic-base/tree/main/archive).
