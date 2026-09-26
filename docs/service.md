# Running the service

The library half checks logs you already have. The service is for when you want the record
itself: every run an agent makes, kept per tenant under audit, so the person it worked for, an
auditor or an incident responder can ask about it later. It is an optional extra:

```bash
pip install 'surf-agentic-base[service]'
```

## What it stores, and what it refuses

Each record says who the run acted for, what class of data it touched and on which tier, whether
personal data was removed from the transcript and by what, who approved which action, and whether
the person was told they were dealing with an AI. Only the tenant and the code revision are
required, so a writer that does not know the rest yet still writes. The terms are defined in
[Concepts](concepts.md).

It refuses three things at the write path:

- **An outcome with no scorer.** `POST /runs` with `resolved: true` and no `label_source` returns
  HTTP 422. A token may only assert the citable scorers its entry in `API_TOKENS` grants.
- **Personal data on the shared tier.** A run classified `personal` or `health` that names the
  `community` isolation tier is rejected.
- **A transcript it could not redact.** With redaction configured, a write that redaction cannot
  process is refused rather than stored as received.

Every create, label and approval joins a per-tenant hash chain, and `GET /runs/integrity` reports
what it verified. A person can be erased on request or on a schedule with the chain still
verifying. A tenant takes its whole corpus away in one request, in the shape the write path
accepts.

## An agent that works for people

`examples/service_agent.py` records a merge-request review agent's runs through the client: who
each review was for, the data class and tier, how the person was told it was an AI, a maintainer's
approval, and three verdicts of different standing. Then it reads back everything the agent did
for one person, and checks the records are intact.

```bash
pip install 'surf-agentic-base[service]'
export API_TOKENS='{"example-token-0000001": {"tenants": ["example-team", "platform-team"], "label_sources": ["official_harness", "human"]}}'
REDACTION=patterns just run          # in one terminal
python examples/service_agent.py     # in another
```

```text
1. Three reviews, each recorded for the person who asked
   recorded 3 runs

2. The agent wanted to push to mr-103; a maintainer decided
   approval recorded

3. Verdicts on the reviews, and which of them mean anything
   mr-101  the developer's thumbs-up    user_feedback  diagnostic
   mr-102  another model's score        model_judge    diagnostic
   mr-103  the maintainer's decision    human          authoritative

4. Everything the agent did for alice, from the tenant's export
   mr-101: Automated review: Looks fine; one missing test for the retry path.
     told it was an AI: every review comment begins 'Automated review:'
     data class internal, tier virtualised
     approvals: none
     stored question: Review mr-101. Questions to <EMAIL_ADDRESS>.
   mr-103: Automated review: Suggest a fix: pin the base image by digest. Push it?
     told it was an AI: every review comment begins 'Automated review:'
     data class internal, tier virtualised
     approvals: approved by urn:example:maintainer-carol
     stored question: Review mr-103. Questions to <EMAIL_ADDRESS>.

5. Are the records as they were written?
   intact: 3 runs match 7 entries
```

## Recording and asking

`examples/record_and_ask.py` records runs from a stand-in agent, including one that crashes,
labels them, and asks the service whether the comparison is sound, whether the records are
intact, what was kept of a transcript, and for one run in W3C PROV.

```bash
pip install 'surf-agentic-base[service,provenance]'
export API_TOKENS='{"example-token-0000001": {"tenants": ["example-team", "platform-team"], "label_sources": ["official_harness", "human"]}}'
REDACTION=patterns just run        # in one terminal
python examples/record_and_ask.py  # in another
```

```text
1. Recording 12 runs to http://localhost:8080
   the run that crashed was kept: status=failed, failure_kind=RuntimeError

2. Labelling the finished runs with the benchmark's own harness
   a label that names no scorer is refused: HTTP 422

3. Is the comparison sound?
   inconclusive: too little data — timeout: 33.3% (with-planner) vs 0.0% (baseline), 95% interval -12.3 to +70.0 pp
   baseline: assessed 6; excluded 0 (none); analysed 6
   with-planner: assessed 6; excluded 2 (2 timeout); analysed 4

4. Are the records as they were written?
   intact: 12 runs match 22 entries

5. What was stored of the transcript
   (the crashed run has no transcript)
   Fix task-1. Mail the report to <EMAIL_ADDRESS>.
   redaction: agentic-base <version> patterns, no names or places

6. One run in W3C PROV, for a reader that is not this service
   sections: activity, agent, entity, prefix, used, wasAssociatedWith, wasAttributedTo, wasGeneratedBy
   the outcome: {"ab:authority": "authoritative", "ab:degraded": false, "ab:instrument": "harness-1.4", "ab:label_source": "official_harness", "ab:resolved": true}

7. Everything this tenant recorded, to take elsewhere
   manifest says 12 records; the file has 12
   the same request without the token: HTTP 401
```

`<version>` is the installed package version.

## Tokens and local development

```bash
just run          # uvicorn with reload on :8080
just check        # tests with coverage, ruff, mypy
```

SQLite by default, so it runs with no infrastructure; PostgreSQL in every deployed environment.

Every data route requires a bearer token. `API_TOKENS` maps each token to the tenants it may use,
`["*"]` for all of them. A token may instead map to `{"tenants": [...], "label_sources": [...]}`;
only the citable sources named there may be asserted through it, and the plain list shape grants
none, so a writer token records diagnostic outcomes and cannot mint citable results. With no
tokens set the service refuses every data request and says what to set. `AUTH=none` turns the
check off for local development and logs a warning when the service starts that way.

```bash
AUTH=none just run
```

A release migrates the schema before it starts, with `agentic-base-migrate`, and the service
refuses to run against an older schema. What the service emits, and where to point it, is in
[Observability](OBSERVABILITY.md).

## From a chat client

`agentic-base-mcp` serves the same database read-only over MCP, with four tools: `list_runs`,
`get_run`, `validity_report` and `corpus_stats`. It opens the database itself, so it runs where
its user may already read the database and is never published as a network service.
`MCP_TENANTS` names the tenants it may serve: without it the server refuses to start, and `*`
serves every tenant deliberately, with a warning.

```json
{
  "mcpServers": {
    "agentic-base": {
      "command": "agentic-base-mcp",
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/agentic-base.db",
        "MCP_TENANTS": "example-team"
      }
    }
  }
}
```

`get_run` returns a long transcript in pages: `transcript.next_message` says where the next page
starts. A page holds at most `AP_MCP_MAX_TRANSCRIPT_CHARS` characters of messages, 60,000 unless
set, and `0` removes the limit. `list_runs` returns at most `AP_MCP_MAX_ROWS` rows, 200 unless
set, and says how many there were.

## Exporting

A run can be served in W3C PROV, OpenLineage or a Process Run Crate (`agentic_base.provenance`),
each through that standard's own library, and a tenant's runs exported to MLflow with
`agentic-base-mlflow`.
