"""The redaction seam: what a redactor is, and how one is applied to a run record.

Detection is not written here. The adapter in ``redaction.presidio`` adopts Presidio, and any
other instrument fits the same protocol. What lives here is the rule for where redaction applies
and what the record says about it afterwards.

Three rules.

The instrument names itself on the record. ``redaction`` carries the name, the version and the
mode, so a transcript redacted by patterns alone cannot be read as one from which names were
removed.

The record says how much was examined. ``extra["redaction"]`` holds the number of strings passed
to the instrument and the findings per entity type, so zero findings reads as zero findings and
not as an instrument that saw nothing.

A record already redacted is left alone. The writer that redacted knows what it ran; a second
pass would overwrite that with a claim about a transcript it did not see in its original form.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agentic_base.domain.outcomes import RunRecordCreate

NOT_REDACTED = "none"


@dataclass(frozen=True)
class Redacted:
    """One string after redaction, and what was found in it."""

    text: str
    found: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class Redactor(Protocol):
    """What an instrument implements to redact a transcript."""

    @property
    def instrument(self) -> str:
        """Name, version and mode, as written into ``RunRecordCreate.redaction``."""
        ...

    def redact(self, text: str) -> Redacted:
        """Return the text with personal data replaced, and the counts per entity type."""
        ...


def redact_run(record: RunRecordCreate, redactor: Redactor) -> RunRecordCreate:
    """Redact the system prompt and every text in the messages, and say so on the record.

    Message content may be a string or a list of parts; tool-call arguments are strings too.
    Every string reached is passed to the redactor, keys and structure are kept. A record whose
    ``redaction`` is not ``none`` is returned unchanged.
    """
    if record.redaction != NOT_REDACTED:
        return record

    found: Counter[str] = Counter()
    examined = 0

    def _text(value: str) -> str:
        nonlocal examined
        examined += 1
        result = redactor.redact(value)
        found.update(result.found)
        return result.text

    def _walk(value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            return _text(value) if key in _TEXT_KEYS else value
        if isinstance(value, dict):
            return {k: _walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v, key) for v in value]
        return value

    system_prompt = _text(record.system_prompt) if record.system_prompt else ""
    messages = [_walk(message) for message in record.messages]
    extra = {
        **record.extra,
        "redaction": {"examined": examined, "found": dict(sorted(found.items()))},
    }
    return record.model_copy(
        update={
            "system_prompt": system_prompt,
            "messages": messages,
            "redaction": redactor.instrument,
            "extra": extra,
        }
    )


#: Keys whose string values are transcript text. Roles, ids, tool names and types are not.
_TEXT_KEYS = frozenset(
    {"content", "text", "arguments", "output", "reasoning", "reasoning_content"}
)
