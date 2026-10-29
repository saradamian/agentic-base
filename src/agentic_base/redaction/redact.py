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

from agentic_base.domain.outcomes import Approval, RunRecordCreate


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


class _Pass:
    """One redactor applied to many strings, and the count of what it examined and found."""

    def __init__(self, redactor: Redactor) -> None:
        self.redactor = redactor
        self.examined = 0
        self.found: Counter[str] = Counter()
        self.instruments: Counter[str] = Counter()

    def text(self, value: str) -> str:
        self.examined += 1
        result = self.redactor.redact(value)
        self.found.update(result.found)
        self.instruments[result.instrument or self.redactor.instrument] += 1
        return result.text

    def data(self, value: Any) -> Any:
        """Every string inside *value*, whatever its key."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.data(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.data(v) for v in value]
        return value

    def part(self, value: Any) -> Any:
        """A message, or one part of one: its structural keys are kept, everything else is data.

        Only the message itself and the parts listed under its ``content`` and ``tool_calls`` are
        structure. A tool's input, a part's metadata and ``extra`` are data at every depth, so an
        ``id`` that holds an e-mail address there is redacted like any other string.
        """
        if not isinstance(value, dict):
            return self.data(value)
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _STRUCTURAL_KEYS and isinstance(item, str):
                out[key] = item
            elif key in _PART_LISTS and isinstance(item, list):
                out[key] = [self.part(element) for element in item]
            else:
                out[key] = self.data(item)
        return out

    def approval(self, approval: Approval) -> Approval:
        """What was approved and the note are redacted. Who decided is kept: recording that
        person is what an approval is for, and erasure removes it when it must go."""
        return approval.model_copy(
            update={
                "action": self.text(approval.action) if approval.action else "",
                "note": self.text(approval.note) if approval.note else "",
            }
        )

    def summary(self, writer: str) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "found": dict(sorted(self.found.items())),
            "instruments": dict(sorted(self.instruments.items())),
            "writer": writer,
        }


def redact_run(record: RunRecordCreate, redactor: Redactor) -> RunRecordCreate:
    """Redact every free-text field of a run, and say so on the record.

    The system prompt, the messages, ``extra``, each approval's action and note, and
    ``failure_kind`` pass through the redactor. ``failure_kind`` is free text that the audit log
    keeps as a value, where no erasure can reach it later. Messages are walked recursively and
    every string is redacted except the structural ones that join a transcript together (roles,
    part types, and the ids that tie a tool call to its result), and those only where the
    transcript's structure puts them. Keys and structure are kept. The writer's ``redaction``
    claim is stored under ``extra["redaction"]["writer"]`` and does not decide whether the
    redactor runs. ``RedactionUnavailable`` propagates: a record is either redacted as declared
    or not written.
    """
    run = _Pass(redactor)
    system_prompt = run.text(record.system_prompt) if record.system_prompt else ""
    messages = [run.part(message) for message in record.messages]
    walked_extra = run.data(record.extra)
    approvals = [run.approval(approval) for approval in record.approvals]
    failure_kind = run.text(record.failure_kind) if record.failure_kind else ""
    ran = sorted(run.instruments) or [redactor.instrument]
    return record.model_copy(
        update={
            "system_prompt": system_prompt,
            "messages": messages,
            "approvals": approvals,
            "failure_kind": failure_kind,
            "redaction": " | ".join(ran),
            "extra": {**walked_extra, "redaction": run.summary(record.redaction)},
        }
    )


def redact_approval(
    approval: Approval, redactor: Redactor
) -> tuple[Approval, dict[str, Any]]:
    """An approval added after its run was written, redacted as the run's own were, and what
    this pass examined and found, for :func:`add_counts`."""
    one = _Pass(redactor)
    redacted = one.approval(approval)
    return redacted, {
        "examined": one.examined,
        "found": dict(one.found),
        "instruments": dict(one.instruments),
    }


def add_counts(counts: dict[str, Any], added: dict[str, Any]) -> dict[str, Any]:
    """A run's ``extra["redaction"]`` with a later pass's counts added; the writer's claim kept."""

    def _sum(key: str) -> dict[str, int]:
        total = Counter(counts.get(key, {})) + Counter(added.get(key, {}))
        return dict(sorted(total.items()))

    return {
        **counts,
        "examined": counts.get("examined", 0) + added.get("examined", 0),
        "found": _sum("found"),
        "instruments": _sum("instruments"),
    }


#: Keys whose string values hold a transcript together rather than carry its text: the role and
#: part type that select a code path, and the ids that join a tool call to its result. Redacting
#: these would break the joins. They are kept only in a message and in the parts under
#: :data:`_PART_LISTS`; anywhere else the same key is data.
_STRUCTURAL_KEYS = frozenset({"role", "type", "id", "tool_call_id", "tool_use_id"})

#: The lists inside a message whose elements are themselves parts of the transcript.
_PART_LISTS = frozenset({"content", "tool_calls"})
