"""Tamper-evident run records.

Both regimes the platform has to answer to ask for records that can be shown to be intact. The
AI Act asks providers of high-risk systems to keep automatically generated logs. The Dutch
Cybersecurity Act, in force since August 2026, asks in-scope entities for incident handling and
logging that stands up afterwards. In both cases a record that could have been edited after the
fact is weaker evidence than one that could not.

The mechanism here is deliberately modest. Each record gets a content hash over its
audit-relevant fields, and each hash includes the previous one for its tenant, so removing or
altering a record breaks every hash after it. This is a hash chain, not a ledger and not a
signature. It detects tampering by anyone who does not rewrite the whole chain, which covers
accident and casual edits. It does not defend against an attacker with write access to the
database and the will to recompute, and it should never be described as if it does.

Verification is a separate function from creation so it can be run on demand and on a schedule,
which is what makes it evidence rather than decoration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
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
    "status",
    "failure_kind",
    "resolved",
    "label_source",
    "degraded",
    "instrument",
)
"""Fields covered by the hash.

Deliberately excludes the transcript. A transcript can be very large and is stored alongside
rather than inline, so hashing it here would make verification cost the whole corpus. What is
covered is the part an audit turns on: what ran, under what configuration, what was decided, and
who decided it.
"""


def _canonical(values: dict[str, Any]) -> bytes:
    """Stable bytes for a mapping, so the same record always hashes the same way."""
    return json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def content_hash(record: Any, previous_hash: str = GENESIS) -> str:
    """Hash of a record's audit fields, chained to the previous record for its tenant."""
    values = {field: getattr(record, field, None) for field in AUDIT_FIELDS}
    values["previous_hash"] = previous_hash
    return hashlib.sha256(_canonical(values)).hexdigest()


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
