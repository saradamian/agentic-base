# When something goes wrong, and who has to be told

Two clocks can start on the same day, they run to different people, and neither notification
discharges the other. This page is what to reach for when one starts, and what this repository
can hand you for it.

It is an engineering runbook, not legal advice, and the questions about which entity is in scope
are for counsel and the compliance officer. It says where the evidence lives and what the
deadlines are, because a clock is only meetable if the evidence exists before it starts.

## The two clocks

**A significant incident** in the service, under the Cyberbeveiligingswet, the Dutch
implementation of NIS2, in force since 15 August 2026. Early warning within 24 hours,
notification within 72, final report within a month. For education and research the intended
incident response team is SURFcert, and the intended start date for higher education is March
2027, so the counterpart and the date are the sector's rather than the generic ones.

**An actively exploited vulnerability in the software**, under the Cyber Resilience Act,
reportable since 11 September 2026. Early warning within 24 hours, notification within 72, and a
final report no later than 14 days after a fix exists. It goes to the single reporting platform
that the European agency for cybersecurity runs, which passes it to the coordinating incident
response team and to the agency at once, so one report reaches everyone who needs it.

The thresholds differ, the recipients differ, and the last deadline differs. An incident in the
running service can be one, the other, or both.

## The first hour

1. **Write down when you became aware.** Every deadline counts from that moment, not from the
   commit that caused it, and it is the one fact nobody can reconstruct later.
2. **Tell a person, not a system.** For the service, the security officer of the team that runs
   the tenant, and SURFcert. For the software, whoever has been named for the vulnerability duty
   below.
3. **Do not close the door on the evidence.** Do not rotate away the logs, redeploy over the
   affected version, or delete records while the shape of it is still unknown. Rotate credentials,
   which is different.
4. **Preserve what a report will need.** The run records for the window, the deployed image
   digest, the configuration hash, and the versions of everything the release attested.

## What this repository can give you

| a report asks for | where it is |
|---|---|
| what ran, when, under what configuration | the run record: model, endpoint, precision, code revision, configuration fingerprint, component versions |
| whether the records have been altered since | `GET /runs/integrity?tenant=...`, which recomputes the audit log the service appends to on every create, label and approval, names the first entry that diverges, and lists runs that differ from their last entry or have none |
| who the runs acted for and what class of data they touched | `principal`, `classification`, `isolation_tier` on every record |
| whether a person approved the action | `approvals` on the record |
| what was in the affected transcripts | the transcripts, redacted as `redaction` on each record describes |
| which dependencies were in the affected release | the lock file at that tag, for the library and every extra; the SBOM attested with a release lists the library as installed on Python 3.10 |
| that the release is the one we published | `gh attestation verify <file> --repo saradamian/agentic-base`, which needs GitHub CLI 2.49 or later |
| everything for one tenant, for a regulator or for the tenant | `GET /runs/export?tenant=...` |

What it cannot give you is the report itself, the decision that an incident is significant, or
the relationship with the recipient. Those are the organisation's.

## What is still open, and who has to close it

**Nobody is named for the software's vulnerability duty.** `SECURITY.md` names a channel and a
response window, which is most of what a coordinated disclosure process needs, but a duty that
belongs to everyone belongs to no one. One person, named, who receives a report and starts the
clock.

**The scope question under the Cyber Resilience Act is unanswered.** Free and open-source
software supplied outside a commercial activity is largely out of scope; an *open-source software
steward*, an entity that supports software it does not sell, carries lighter duties from
11 December 2027. Which of those describes SURF publishing this package decides whether anything
is owed at all, and it is a question for counsel rather than for this page. The technical evidence
either answer would need is already produced by the release.

**Nobody holds an account on the reporting platform.** A first report is the wrong moment to
find out what registering takes.

**The deployed service is unwalked.** The service rows below were walked against a local
instance on SQLite. The first drill after go-live walks them against the real one, with its
PostgreSQL, its redaction model and its tenant.

## The drill

A runbook nobody has walked is a document, not a capability, so this one was walked on
13 September 2026 as a tabletop against v0.3.4. The scenario: an actively exploited
vulnerability in `h11`, which reaches the library through httpx, a core dependency, so every
install is affected and not only the service.

| question | answer | how long |
|---|---|---|
| which version was in the release | `h11` 0.16.0, through httpcore 1.0.9 and httpx 0.28.1, read from the lock at the tag | seconds |
| does the release carry an SBOM | no. The SBOM step was added after v0.3.4, so no release carries one yet | seconds |
| is the file people install the one we published | the wheel on the GitHub release verified. The wheel on PyPI did not: the publish job built the distribution a second time, so what `pip install` fetches had a different hash and no attestation | five seconds, after installing a current GitHub CLI |
| who is told | nobody is named | |
| where the report goes | not tried: it needs an account nobody has | |

What changed because of it. The publish job now uploads the files the release job attested and
verifies each before it does, and a test fails if it builds again; v0.3.4 on PyPI stays as it
was, and the next release is the first whose PyPI wheel verifies. The table above now says which
version of the GitHub CLI the verify command needs, because the responder's machine had one from
2022 without it. And it says what the SBOM covers, the library installed on the consumer floor,
so that for the service extras the lock at the tag is the answer.

The service rows were walked the next day, against a local instance holding three runs for one
tenant, a label and an approval.

| question | answer | how long |
|---|---|---|
| what ran, when, under what configuration | the record, by id | under 10 ms |
| whether the records have been altered | `GET /runs/integrity`: intact over three runs and five entries, and after one field was changed directly in the database, not intact, naming that run | under 10 ms |
| who the runs acted for, what data, who approved | the export: principals, classifications and the approval | under 10 ms |
| what was in the transcripts | the export, with an email address replaced by its entity type and `redaction` naming the instrument | under 10 ms |

The first attempt could not answer the second row at all. The hash chain existed as a library and
nothing wrote it: no hash was stored and nothing verified one, while the pages said the service
chained its records. The service now appends an entry to an audit log with every create, label
and approval, and the endpoint above verifies it. The walk also found that the export carried no
run id and no time, so it could not say which run happened when, and that timestamps came back
without their zone. Both are fixed.
