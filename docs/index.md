# surf-agentic-base

The record and referee for agent runs, the security primitives an agent needs on a shared
platform, and the engineering standard that keeps both honest. The contracts layer under SURF's
capability blocks.

The [readme](include-readme.md) covers the service in a page. After that:

- [Blocks and layers](architecture/blocks.md): the design, what exists behind each block, and the order to build
- [Reuse ledger](architecture/reuse-ledger.md): what is adopted, bridged, or built, and why
- [The engineering standard](ENGINEERING.md): what each rule cost, and the test that enforces it
- [Observability](OBSERVABILITY.md): what the service emits and where to point it
- [From agentic-env](architecture/from-agentic-env.md): what was extracted, what was left, what the first consumer found
- [Going live on SDP](architecture/go-live-on-sdp.md): the deployment repository and the open questions
