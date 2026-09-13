"""The redaction seam: what a redactor is, and how one is applied to a run record.

Three rules.

The instrument names itself on the record. ``redaction`` carries what actually ran on this
record: which detectors, which model and version, and whether a fallback was used. A transcript
redacted by patterns alone cannot be read as one from which names were removed.

The record says how much was examined. ``extra["redaction"]`` holds the number of strings
passed to the redactor, the findings per entity type, and how often each instrument was the one
that ran, so zero findings reads as zero findings and not as an instrument that saw nothing.

A record already redacted is left alone. The writer that redacted knows what it ran; a second
pass would overwrite that with a claim about a transcript it did not see in its original form.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agentic_base.domain.outcomes import RunRecordCreate

NOT_REDACTED = "none"


class RedactionUnavailable(RuntimeError):
    """No configured detector for names and places could run. The transcript must not be
    written as if it had been redacted, and it must not be written unredacted either."""


@dataclass(frozen=True)
class Span:
    """A finding: a half-open character range, its entity type and how confident the detector was."""

    start: int
    end: int
    entity: str
    score: float = 1.0


@dataclass(frozen=True)
class Redacted:
    """One string after redaction, what was found in it, and which instrument ran."""

    text: str
    found: dict[str, int] = field(default_factory=dict)
    instrument: str = ""


@runtime_checkable
class Redactor(Protocol):
    """What an instrument implements to redact a transcript."""

    @property
    def instrument(self) -> str:
        """What this redactor runs when every part of it is available."""
        ...

    def redact(self, text: str) -> Redacted:
        """Return the text with personal data replaced, the counts per entity type, and the
        instrument that actually ran. Raises ``RedactionUnavailable`` rather than under-redact."""
        ...


def replace_spans(text: str, spans: Sequence[Span], instrument: str = "") -> Redacted:
    """Replace every span with ``<ENTITY>``.

    Overlapping spans become one span covering all of them, labelled by the most confident and
    on a tie the longest. A partial overlap therefore removes the union, which errs towards
    removing too much rather than leaving half a name.
    """
    merged: list[list[Any]] = []
    for s in sorted(spans, key=lambda s: (s.start, -s.end)):
        if merged and s.start < merged[-1][1]:
            current = merged[-1]
            current[1] = max(current[1], s.end)
            if (s.score, s.end - s.start) > (current[3], current[4]):
                current[2], current[3], current[4] = s.entity, s.score, s.end - s.start
        else:
            merged.append([s.start, s.end, s.entity, s.score, s.end - s.start])
    out = text
    for start, end, entity, _, _ in reversed(merged):
        out = out[:start] + f"<{entity}>" + out[end:]
    return Redacted(
        text=out, found=dict(Counter(m[2] for m in merged)), instrument=instrument
    )


def redact_run(record: RunRecordCreate, redactor: Redactor) -> RunRecordCreate:
    """Redact the system prompt and every text in the messages, and say so on the record.

    Message content may be a string or a list of parts; tool-call arguments are strings too.
    Every string reached is passed to the redactor; keys and structure are kept. A record whose
    ``redaction`` is not ``none`` is returned unchanged. ``RedactionUnavailable`` propagates: a
    record is either redacted as declared or not written.
    """
    if record.redaction != NOT_REDACTED:
        return record

    found: Counter[str] = Counter()
    instruments: Counter[str] = Counter()
    examined = 0

    def _text(value: str) -> str:
        nonlocal examined
        examined += 1
        result = redactor.redact(value)
        found.update(result.found)
        instruments[result.instrument or redactor.instrument] += 1
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
    ran = sorted(instruments) or [redactor.instrument]
    extra = {
        **record.extra,
        "redaction": {
            "examined": examined,
            "found": dict(sorted(found.items())),
            "instruments": dict(sorted(instruments.items())),
        },
    }
    return record.model_copy(
        update={
            "system_prompt": system_prompt,
            "messages": messages,
            "redaction": " | ".join(ran),
            "extra": extra,
        }
    )


#: Keys whose string values are transcript text. Roles, ids, tool names and types are not.
_TEXT_KEYS = frozenset(
    {"content", "text", "arguments", "output", "reasoning", "reasoning_content"}
)
