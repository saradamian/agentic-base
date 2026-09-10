# What this platform produces for AI Act and NIS2 evidence

Scope note. This is an engineering mapping, not legal advice, and the classification questions
below need a lawyer and a compliance officer. What it does is say which obligations produce a
technical requirement, and which of those requirements this platform already meets.

## The two regimes, and where they actually bite

### AI Act

Obligations for general-purpose model providers have applied since August 2025, and the
Commission's supervision and enforcement powers came into force on 2 August 2026. Penalties for a
provider reach 15 million euro or 3 percent of worldwide turnover.

The articles that turn into engineering:

| article | obligation | what it asks for |
|---|---|---|
| 11 and Annex IV | technical documentation before a high-risk system is placed on the market | a description of the system, its development, its data, and its performance |
| 12 | record-keeping | high-risk systems must technically allow automatic recording of events over the system's lifetime |
| 15 | accuracy, robustness, cybersecurity | declared performance, and evidence for it |
| 19 | log retention | providers keep the logs their systems generate, at least six months |
| 53 and 55 | general-purpose model providers | technical documentation, a training-data summary, and for systemic-risk models evaluation, adversarial testing and incident reporting |
| 57 to 61 | regulatory sandboxes | supervised testing with evidence |
| 72 | post-market monitoring | a plan, and data to run it against |

Timing worth knowing: Article 12 applies from 2 December 2027 for Annex III high-risk systems and
2 August 2028 for Annex I. So the logging obligation is not yet enforceable, and building for it
now is cheap while retrofitting it later is not.

### NIS2, as Dutch law

The Netherlands transposed NIS2 as the Cyberbeveiligingswet. The Senate adopted it on 7 July 2026
and it entered into force on **15 August 2026**, so this one is live now.

Research organisations sit in the directive's second annex, which makes an in-scope entity an
*important* entity, not an essential one. The size threshold is 50 staff or 10 million euro.
Penalties for important entities reach 7 million euro or 1.4 percent of turnover. Whether a
particular SURF entity is in scope, and under which sector, is a question for counsel and not one
this document answers.

Two articles turn into engineering. Article 21 lists ten risk-management measures, of which
incident handling, supply-chain security, vulnerability handling, and logging are the ones a
platform can serve directly. Article 23 sets the reporting clock: an early warning within 24
hours, a notification within 72, and a final report within a month. That clock is the real
requirement, because it is only meetable if the evidence already exists when the incident is
found.

## What the platform already produces

| requirement | what serves it here |
|---|---|
| automatic event recording over a system's lifetime | the run record, written while the run happens, not reconstructed after |
| evidence that a record has not been altered | the hash chain in `app.domain.integrity`, verifiable on demand |
| provenance of a performance claim | `label_source`, which refuses citability to a self-reported or convenience-scored outcome |
| evidence that a verdict came from a working instrument | `degraded` and `instrument` |
| reproducibility of a reported result | model, endpoint, precision, code revision and configuration fingerprint on every record |
| soundness of a comparison between configurations | `app.domain.validity` |
| data and workflow provenance in a standard format | PROV, RO-Crate and OpenLineage emission |
| dependency and supply-chain evidence | Dependency Track through the platform pipeline, on every build |
| vulnerability handling | the same, plus Renovate |
| access control and authentication | SURFconext and SRAM through the platform |
| log aggregation and retention | Loki and Prometheus through the platform |

The platform's own principles already require audit and reporting functions that demonstrate its
core controls, so most of the second half of that table is inherited.

## What is missing, and should be said out loud

- **Retention is not enforced.** Six months is a policy that nothing currently applies. A record
  can be deleted and the chain will detect it, which is not the same as preventing it.
- **No incident workflow.** The 24, 72 and 30 day clock needs a path from detection to a report,
  and there is none here. What exists is the evidence such a report would draw on.
- **No human oversight record.** Article 14 expects oversight measures for high-risk systems.
  Approvals, overrides and interventions are not modelled.
- **No data classification.** Sensitive-data handling is the AI Factory's central commitment, and
  nothing in the record says what class of data a run touched.
- **The chain is not a ledger.** It detects tampering by anyone who does not rewrite it wholesale.
  It is not a signature and not an append-only store, and it must not be presented as either.
- **No conformity documentation generator.** Annex IV asks for a document. The material for one is
  here; assembling it is not.

## The honest summary for a conversation

The platform is well placed on evidence generation and poorly placed on process. Every obligation
that reduces to "record what happened in a way that survives scrutiny" is largely met, because
that is what this project is for. Every obligation that reduces to "have a procedure and follow
it" is not met and mostly should not be met here, because it belongs to an organisation rather
than to a service.

The useful claim is therefore narrow: this is the layer that makes AI Act and NIS2 evidence a
by-product of running the work, instead of a project someone has to staff after the fact.
