# What this platform produces as regulatory evidence

Scope note. This is an engineering mapping, not legal advice, and the classification questions
below need a lawyer and a compliance officer. What it does is say which obligations produce a
technical requirement, and which of those requirements this platform already meets.

## What is already in force, read on 2026-09-13

Four regimes bite before the high-risk AI rules do, and two of them are newer than the rest of
this page.

| in force | what it asks of a platform like this |
|---|---|
| AI Act, prohibited practices, since 2 February 2025 | nothing here |
| AI Act, general-purpose model provider duties, since 2 August 2025 | nothing here: SURF is not the provider of the models it serves |
| AI Act, **article 50 transparency**, since 2 August 2026 | a person is told they are dealing with an AI, and generated content is marked. This is live, not future |
| AI Act, Commission enforcement powers, since 2 August 2026 | the evidence has to exist when it is asked for |
| **NIS2 as the Cyberbeveiligingswet, since 15 August 2026** | registration, a duty of care, and the reporting clock. The intended date for higher education is March 2027, and SURFcert is the intended incident response team for the sector, so the sector's clock and its counterpart are not the generic ones |
| **Cyber Resilience Act, article 14, since 11 September 2026** | a manufacturer of a product with digital elements reports an actively exploited vulnerability: early warning in 24 hours, notification in 72, final report 14 days after a fix exists |
| **Data Act, since 12 September 2025** | a customer of a data processing service can switch away and take data and digital assets with them, within 30 days of a two-month notice; from 12 January 2027 without a switching charge |
| AI Act, high-risk, Annex III from 2 December 2027 and Annex I from 2 August 2028 | record-keeping, documentation, human oversight. Deferred by the Digital Omnibus, not cancelled |

## The regimes, and where they actually bite

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

Timing. The Digital Omnibus (Regulation (EU) 2026/1744, in force 27 July 2026) moved the Annex
III high-risk obligations, article 12 among them, to 2 December 2027 and the Annex I ones to
2 August 2028. The requirement did not change, only the date. Building for it now is cheap;
retrofitting it is not.

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

Two dates matter beside the general one. The law has applied since 15 August 2026, and the
intended date for higher education is March 2027; SURFcert is the intended incident response team
for this sector. So the counterpart an incident is reported to, and the date it starts, are the
sector's, not the generic ones. Registration with the national centre is an organisational duty
and belongs to SURF, not to this service.

### Cyber Resilience Act

The one nobody on this project had written down, and its first obligation started on
11 September 2026: a manufacturer of a product with digital elements reports an actively
exploited vulnerability in it, within 24 hours, 72 hours and then 14 days after a fix exists. The
rest of the regulation applies from 11 December 2027, and the obligations of an *open-source
software steward*, a lighter category for an entity that supports open-source software it does
not sell, apply from the same date.

Which category this repository falls into is a question for counsel, and the answer decides
whether anything is owed at all: software supplied free and open source outside a commercial
activity is largely out of scope, while a steward carries a security policy, coordinated
disclosure and reporting duties. What is worth saying as engineering is that the technical
evidence the regulation asks a manufacturer for, an SBOM, a vulnerability handling process, a
disclosure channel, and updates, is mostly what this repository already produces: an SBOM and
build provenance attested on every release, a private reporting channel and a stated response
window in `SECURITY.md`, a dependency review and an advisory audit on every change, and a secret
scan over files and history. The missing piece is not a mechanism but a decision and a named
person.

### Data Act

Applicable since 12 September 2025. If the runs service is offered to tenants as a data
processing service, its customers may leave and take their data and digital assets with them:
a switching process started on at most two months' notice and completed within 30 days, and from
12 January 2027 with no charge for it.

That is a design requirement rather than a legal one for us to answer, and it is met for the
data: `GET /runs/export?tenant=...` streams a tenant's whole corpus as newline-delimited JSON,
one run per line in the shape the write path accepts, after a manifest line that says how many
records follow. The manifest is what makes a truncated download visible, and the shape is what
makes the file replayable into another instance rather than merely readable. A single run also
comes in W3C PROV, OpenLineage or an RO-Crate for a reader that is not this service.

What is still missing is the rest of a switching process: an agreed format for the tenant's
configuration, and the platform-side steps for closing an account, neither of which belongs to
this service alone.

## What the platform already produces

| requirement | what serves it here |
|---|---|
| automatic event recording over a system's lifetime | the run record, written while the run happens, not reconstructed after |
| evidence that a record has not been altered | the hash chain in `agentic_base.domain.integrity`, verifiable on demand. It detects an edit; it is not a signature and not an append-only store |
| who a run acted for, what class of data it touched, who approved what | `principal`, `classification`, `isolation_tier`, `approvals` on every record |
| provenance of a performance claim | `label_source`, which refuses citability to a self-reported or convenience-scored outcome |
| evidence that a verdict came from a working instrument | `degraded` and `instrument` |
| reproducibility of a reported result | model, endpoint, precision, code revision and configuration fingerprint on every record |
| soundness of a comparison between configurations | `agentic_base.domain.validity` |
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
- **Human oversight is recorded, not required.** Article 14 expects oversight measures for
  high-risk systems. The record carries approvals, overrides and interventions with who decided
  and when, and an endpoint to add one; nothing yet forces a block to obtain one before it acts.
- **Data classification is recorded, not enforced by the tenant.** Sensitive-data handling is the
  AI Factory's central commitment. Every run carries the class of data it touched and the
  isolation tier it ran under, and personal or health data on the community tier is refused;
  what is not built is the tenant's use case setting both, so today the writer states them.
- **The chain is not a ledger.** It detects tampering by anyone who does not rewrite it wholesale.
  It is not a signature and not an append-only store, and it must not be presented as either.
- **No conformity documentation generator.** Annex IV asks for a document. The material for one is
  here; assembling it is not.
- **Article 50 is recorded, not discharged.** A person must be told they are dealing with an AI,
  and synthetic content must be marked machine-readably. Both happen where an agent speaks to a
  person, which is the channels block, and that block does not exist. What exists since this was
  written is the record: `disclosure` names how the person was told, `content_marking` names the
  standard and identifier the output carries, and both default to `none`, so a corpus can separate
  runs that predate the answer from runs that lack it.

  For images, audio and video the Commission's draft code of practice names Content Credentials
  (C2PA) as its example, and there is an Apache-licensed implementation to adopt when the channels
  block needs one. For text there is no equivalent open format: the published schemes are either
  metadata beside the text, which does not survive copying, or proprietary token watermarking. So
  for a text channel the honest reading of article 50(2) is a disclosure the person sees, recorded
  in `disclosure`, and `content_marking` left at `none` with that fact visible rather than a
  standard invented here.
- **No decision on the Cyber Resilience Act.** Whether this is out of scope, or a steward's
  obligation from December 2027, is unanswered, and the answer changes who reports what.

## The summary for a conversation

The platform is well placed on evidence generation and poorly placed on process. Every obligation
that reduces to "record what happened in a way that survives scrutiny" is largely met, because
that is what this project is for. Every obligation that reduces to "have a procedure and follow
it" is not met and mostly should not be met here, because it belongs to an organisation rather
than to a service.

The useful claim is therefore narrow: this is the layer that makes AI Act and NIS2 evidence a
by-product of running the work, instead of a project someone has to staff after the fact.
