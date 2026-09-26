"""The redaction seam: what a redactor is, and how one is applied to a run record.

Three rules.

The server's configuration decides what runs. The writer's ``redaction`` field is kept as the
writer's claim, under ``extra["redaction"]["writer"]``, and gates nothing: a field any writer
can set must not be the thing that turns the server's redaction off.

The instrument names itself on the record. ``redaction`` carries what actually ran on this
record: which detectors, which model and version, and whether a fallback was used. A transcript
redacted by patterns alone cannot be read as one from which names were removed.

The record says how much was examined. ``extra["redaction"]`` holds the number of strings
passed to the redactor, the findings per entity type, and how often each instrument was the one
that ran, so zero findings reads as zero findings and not as an instrument that saw nothing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agentic_base.domain.outcomes import RunRecordCreate


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
    """Redact every string in the transcript and in ``extra``, and say so on the record.

    The system prompt, the messages and ``extra`` are walked recursively; every string value is
    passed to the redactor, wherever it nests, except values under the structural keys that
    join parts of a transcript together (roles, part types, and the ids that tie a tool call
    to its result). Keys and structure are kept. The writer's ``redaction`` claim is stored
    under ``extra["redaction"]["writer"]`` and does not decide whether the redactor runs.
    ``RedactionUnavailable`` propagates: a record is either redacted as declared or not written.
    """
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
            return value if key in _STRUCTURAL_KEYS else _text(value)
        if isinstance(value, dict):
            return {k: _walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v, key) for v in value]
        return value

    system_prompt = _text(record.system_prompt) if record.system_prompt else ""
    messages = [_walk(message) for message in record.messages]
    walked_extra = _walk(record.extra)
    ran = sorted(instruments) or [redactor.instrument]
    extra = {
        **walked_extra,
        "redaction": {
            "examined": examined,
            "found": dict(sorted(found.items())),
            "instruments": dict(sorted(instruments.items())),
            "writer": record.redaction,
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


#: Keys whose string values hold a transcript together rather than carry its text: the role and
#: part type that select a code path, and the ids that join a tool call to its result. Redacting
#: these would break the joins; everything else, names included, is treated as text.
_STRUCTURAL_KEYS = frozenset({"role", "type", "id", "tool_call_id", "tool_use_id"})
