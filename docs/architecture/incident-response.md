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
| whether the records have been altered since | the hash chain, `agentic_base.domain.integrity.verify_chain`, which names the first record that diverges |
| who the runs acted for and what class of data they touched | `principal`, `classification`, `isolation_tier` on every record |
| whether a person approved the action | `approvals` on the record |
| what was in the affected transcripts | the transcripts, redacted as `redaction` on each record describes |
| which dependencies were in the affected release | the SBOM attested with every release, and the lock file at that tag |
| that the release is the one we published | the build provenance attestation on the release artefacts |
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

**No drill has been run.** A runbook nobody has walked through is a document, not a capability.
The cheapest version is an hour: take last month's release, pretend a vulnerability in a
dependency is being exploited, and see how long it takes to answer the table above.
