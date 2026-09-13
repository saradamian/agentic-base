"""Identifiers found by their shape, with the checksum where one exists. Standard library only.

This is the layer that always runs, before any model and whether or not a model is reachable,
and its findings are masked before text is sent to one: a credential or a bank number in a
transcript never leaves the service for detection.

Checksums carry the precision. An IBAN must pass mod 97, a card number the Luhn check and a
known leading digit, a citizen service number the eleven test, an IP address the standard
library's parser. Phone numbers are matched in international form, or in Dutch national form
with ten digits, because a looser rule redacts job ids and timestamps.

Credentials merge what agentic-env's two corpus scanners each had and the other lacked. A
credential is redacted whatever surrounds it: a token pasted into a shell transcript carries no
label.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass

from agentic_base.redaction.redact import Span

EMAIL = "EMAIL_ADDRESS"
PHONE = "PHONE_NUMBER"
IBAN = "IBAN_CODE"
CARD = "CREDIT_CARD"
IP = "IP_ADDRESS"
BSN = "NL_BSN"
CREDENTIAL = "CREDENTIAL"

PATTERN_ENTITIES: tuple[str, ...] = (CREDENTIAL, EMAIL, PHONE, IBAN, CARD, IP, BSN)


def iban_is_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "").upper()
    if (
        not 15 <= len(compact) <= 34
        or not compact[:2].isalpha()
        or not compact[2:4].isdigit()
    ):
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def luhn_is_valid(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if (
        not 13 <= len(digits) <= 19
        or digits[0] not in (3, 4, 5, 6)
        or len(set(digits)) == 1
    ):
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def bsn_is_valid(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if len(digits) != 9 or sum(digits) == 0:
        return False
    weighted = sum(d * w for d, w in zip(digits[:8], range(9, 1, -1), strict=True))
    return (weighted - digits[8]) % 11 == 0


def phone_is_plausible(candidate: str) -> bool:
    digits = sum(c.isdigit() for c in candidate)
    if candidate.startswith("+"):
        return 8 <= digits <= 15
    return digits == 10 and candidate.lstrip("(").startswith("0")


def ip_is_valid(candidate: str) -> bool:
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class _Rule:
    entity: str
    pattern: re.Pattern[str]
    valid: Callable[[str], bool] | None = None
    group: int = 0


_CREDENTIAL_PATTERNS = (
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}",
    r"\bglpat-[A-Za-z0-9_-]{20,}",
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",
    r"\bgithub_pat_[A-Za-z0-9_]{50,}",
    r"\bhf_[A-Za-z0-9]{34,}",
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"
    r"(?:[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----|[^\n]*)",
    # An API key in the shape Willma issues: twelve hex, then a full UUID. agentic-env's corpus
    # scanner had one UUID group too few and matched no real key.
    r"\b[0-9a-f]{12}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
)

_RULES: tuple[_Rule, ...] = (
    *(_Rule(CREDENTIAL, re.compile(p)) for p in _CREDENTIAL_PATTERNS),
    _Rule(CREDENTIAL, re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{20,})"), group=1),
    _Rule(
        CREDENTIAL,
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)"
            r"[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
        ),
        group=1,
    ),
    _Rule(
        EMAIL,
        re.compile(
            r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"
        ),
    ),
    _Rule(
        IBAN,
        re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"),
        iban_is_valid,
    ),
    _Rule(
        CARD, re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?!\d|\.\d)"), luhn_is_valid
    ),
    _Rule(
        BSN, re.compile(r"(?<![\d.])\d{4}[ .]?\d{2}[ .]?\d{3}(?!\d|\.\d)"), bsn_is_valid
    ),
    _Rule(
        PHONE,
        re.compile(
            r"(?<![\w+-])(?:\+\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}"
            r"|\(?0\d{1,3}\)?[ -]?\d{2,4}(?:[ -]?\d{2,4}){1,2})(?![\w-])"
        ),
        phone_is_plausible,
    ),
    _Rule(
        IP, re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)"), ip_is_valid
    ),
    _Rule(
        IP,
        re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"),
        ip_is_valid,
    ),
)


#: When shapes overlap, the more specific one names the merged span: an IBAN's digit groups also
#: look like a phone number.
_PRECEDENCE = {
    CREDENTIAL: 1.0,
    IBAN: 0.95,
    CARD: 0.9,
    BSN: 0.85,
    EMAIL: 0.8,
    IP: 0.7,
    PHONE: 0.6,
}


class PatternDetector:
    """Find identifiers by shape and checksum."""

    name = "patterns"

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for rule in _RULES:
            for match in rule.pattern.finditer(text):
                value = match.group(rule.group)
                if not value or (rule.valid and not rule.valid(value.strip())):
                    continue
                start, end = match.span(rule.group)
                spans.append(Span(start, end, rule.entity, _PRECEDENCE[rule.entity]))
        return spans
