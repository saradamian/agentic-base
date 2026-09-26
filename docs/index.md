# surf-agentic-base

Two checks for claims about AI agents (did the comparison lose runs unevenly, and who scored each
outcome), and a service that records agent runs so the checks can be made later.

Read these first:

- [The readme](include-readme.md): the two checks, and `agentic-base check` over logs you already have
- [Concepts](concepts.md): the fifteen terms, each pointing at its code
- [Running the service](service.md): worked examples, tokens, MCP, export

Reference, when you need it:

- [Decisions](decisions.md): the choices that are cheap now and expensive to reverse
- [Observability](OBSERVABILITY.md): what the service emits and where to point it
- [Compliance evidence](architecture/compliance.md): what the record produces for the AI Act and NIS2
- [Redaction](architecture/redaction.md): what removes personal data from a transcript, and what each mode catches and costs
- [Incident response](architecture/incident-response.md): the two clocks, who is told, and what this repository hands you
- [Reuse ledger](architecture/reuse-ledger.md): what is adopted, bridged, or built, and why
- [The engineering standard](ENGINEERING.md): what each rule cost, and the test that enforces it
- [Repository process](architecture/process.md): the rulesets, and what the tests assert about the pipeline
- [Going live on SDP](architecture/go-live-on-sdp.md) and [the deployment overlay](architecture/deployment-overlay.md): SURF's deployment

The design vision (twelve capability blocks, the layering, the boundaries against neighbouring
efforts, operational traps carried over from agentic-env) is kept for the record in the
repository's [archive](https://github.com/saradamian/agentic-base/tree/main/archive).
