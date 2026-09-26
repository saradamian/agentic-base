"""Integrity of the run record chain.

Not tamper-evidence against an adversary who rewrites the database wholesale, which this
mechanism cannot resist and must never be described as resisting. It makes the corpus
tamper-evident against everything short of that: an edited record, an edited or reordered
entry, a removed entry, a removed run, and a truncated tail all leave the verification
naming what is wrong.

Both regimes the platform has to answer to ask for records that can be shown to be intact. The
AI Act asks providers of high-risk systems to keep automatically generated logs; the Digital
Omnibus of July 2026 moved the Annex III date to December 2027 and left the requirement as it
was. The Dutch Cybersecurity Act, in force since 15 August 2026, asks in-scope entities for
incident handling and logging that stands up afterwards. In both cases a record that could have
been edited after the fact is weaker evidence than one that could not.

The mechanism is a hash chain, not a ledger and not a signature. Each audit entry hashes its
complete content — its position in the tenant's chain, the run it describes, the event name,
the moment it was written, the audit fields, and a digest of every personal or bulk field — and
each hash includes the previous one for its tenant, so altering or removing an entry breaks
every hash after it, and forging one entry means recomputing every hash that follows. It does
not defend against an attacker with write access to the database and the will to recompute the
whole chain and its head.

Two fields exist for what a broken link alone cannot show:

* a per-tenant sequence number in every entry, hashed, so a gap has a place and a name;
* a head record per tenant, updated in the same transaction as every append, so cutting the
  last entries leaves a head pointing past the end of the log.

Personal data enters the chain only as SHA-256 digests (:data:`DIGEST_FIELDS`), never as
values. That is what lets an erasure remove a person from the run row while every entry, and
the chain over them, stays verifiable: the digests of the erased content remain, the content
does not, and the verification reports the erasure instead of hiding it.

Verification is a separate function from creation so it can be run on demand and on a schedule,
which is what makes it evidence rather than decoration.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GENESIS = "0" * 64
"""The previous hash of the first record in a tenant's chain."""

AUDIT_FIELDS = (
    "run_id",
    "created_at",
    "tenant",
    "item",
    "arm",
    "arm_fingerprint",
    "model",
    "endpoint",
    "precision",
    "code_revision",
    "component_versions",
    "status",
    "failure_kind",
    "resolved",
    "label_source",
    "labelled_at",
    "degraded",
    "instrument",
    "classification",
    "isolation_tier",
    "redaction",
    "disclosure",
    "content_marking",
    "prompt_tokens",
    "completion_tokens",
    "joules",
    "num_steps",
    "total_tool_calls",
    "elapsed_ms",
    "erased_at",
)
"""Fields hashed as values: what ran, under what configuration, what it cost, what was decided.

Deliberately excludes what :data:`DIGEST_FIELDS` covers. Those fields either carry personal
data, which an erasure must be able to remove from everywhere it lives without breaking the
chain, or they are bulk a snapshot per change cannot afford to copy. They are covered by the
hash all the same, as digests.
"""

DIGEST_FIELDS = (
    "principal",
    "approvals",
    "system_prompt",
    "messages",
    "extra",
)
"""Fields hashed as SHA-256 digests of their canonical value, never stored in the log.

``principal`` and ``approvals`` name people, and the transcript is both personal and large;
``extra`` is a writer's free field and has to be assumed personal. A digest makes a forged
value detectable while keeping the log free of the content itself, so erasing the run row
erases the only copy.
"""


def _canonical(values: dict[str, Any]) -> bytes:
    """Stable bytes for a mapping, so the same record always hashes the same way."""
    return json.dumps(
        values, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def snapshot(record: Any) -> dict[str, Any]:
    """A record's audit fields as plain JSON values.

    A database hands back a timestamp without its zone and an enum as its value, so the same
    record read back must produce the same snapshot it produced when written.
    """
    values = {field: _plain(getattr(record, field, None)) for field in AUDIT_FIELDS}
    plain: dict[str, Any] = json.loads(_canonical(values))
    return plain


def digest_value(value: Any) -> str:
    """The SHA-256 digest of one field's canonical value."""
    return hashlib.sha256(_canonical({"value": _plain(value)})).hexdigest()


def field_digests(record: Any) -> dict[str, str]:
    """Digests of the fields the log covers without storing."""
    return {
        field: digest_value(getattr(record, field, None)) for field in DIGEST_FIELDS
    }


def hash_snapshot(values: Mapping[str, Any], previous_hash: str = GENESIS) -> str:
    """Hash of a snapshot, chained to the previous hash for its tenant."""
    return hashlib.sha256(
        _canonical({**values, "previous_hash": previous_hash})
    ).hexdigest()


def entry_hash(
    seq: int,
    run_id: str,
    event: str,
    at: datetime,
    fields: Mapping[str, Any],
    digests: Mapping[str, str],
    previous_hash: str = GENESIS,
) -> str:
    """Hash of an audit entry's complete content, chained to its tenant's previous entry.

    Everything the entry stores is covered: its position, which run, which event, when, the
    audit fields, and the digests of the fields the log does not store. An entry with any of
    it rewritten no longer matches its recorded hash.
    """
    return hash_snapshot(
        {
            "seq": seq,
            "run_id": run_id,
            "event": event,
            "at": _plain(at),
            "fields": dict(fields),
            "digests": dict(digests),
        },
        previous_hash,
    )


def content_hash(record: Any, previous_hash: str = GENESIS) -> str:
    """Hash of a record's audit fields, chained to the previous record for its tenant."""
    return hash_snapshot(snapshot(record), previous_hash)


@dataclass(frozen=True)
class ChainVerdict:
    """Whether a chain is intact, and enough context to read a clean result honestly."""

    intact: bool
    records_checked: int
    first_broken_index: int | None = None
    detail: str = ""

    @property
    def could_have_failed(self) -> bool:
        """False when the input was too short to demonstrate anything.

        An empty or single-record chain verifies trivially. Reporting that as intact without
        saying so invites it to be read as evidence.
        """
        return self.records_checked >= 2

    def summary(self) -> str:
        if not self.could_have_failed:
            return f"inconclusive: {self.records_checked} record(s), too few to verify a chain"
        if self.intact:
            return f"intact: {self.records_checked} records verified"
        return f"broken at index {self.first_broken_index}: {self.detail}"


def build_chain(records: Sequence[Any]) -> list[str]:
    """Hashes for a sequence of records in the order they were written."""
    hashes: list[str] = []
    previous = GENESIS
    for record in records:
        previous = content_hash(record, previous)
        hashes.append(previous)
    return hashes


def verify_chain(records: Sequence[Any], hashes: Iterable[str]) -> ChainVerdict:
    """Recompute a chain and report the first place it diverges."""
    stored = list(hashes)
    if len(stored) != len(records):
        return ChainVerdict(
            intact=False,
            records_checked=min(len(stored), len(records)),
            first_broken_index=min(len(stored), len(records)),
            detail=f"{len(records)} records against {len(stored)} hashes",
        )

    previous = GENESIS
    for index, (record, expected) in enumerate(zip(records, stored, strict=True)):
        actual = content_hash(record, previous)
        if actual != expected:
            return ChainVerdict(
                intact=False,
                records_checked=len(records),
                first_broken_index=index,
                detail="record content does not match its recorded hash",
            )
        previous = actual
    return ChainVerdict(intact=True, records_checked=len(records))
