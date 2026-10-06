# surf-agentic-base

The record of what an AI agent did: who it acted for, on what data, with whose approval, how the
person was told, and who scored the outcome. A service keeps it per tenant under audit and exports
it in the provenance standards. Two checks on claims about agents come out of the same record.

Read these first:

- [The readme](include-readme.md): the record, the service, the tool-server library, and the two checks
- [Concepts](concepts.md): the fifteen terms, each pointing at its code
- [Running the service](service.md): worked examples, tokens, MCP, export
- [Check a comparison](checks.md): the two checks, over the record or over logs you already have

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
