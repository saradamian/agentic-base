"""Patterns always, then a detector for names and places, with a fallback, failing closed.

The order of a redaction:

1. The pattern layer finds credentials, contact details, bank and card numbers, IP addresses and
   citizen service numbers. It needs nothing and cannot be unavailable.
2. Those findings are masked, character for character, so offsets are unchanged and nothing the
   patterns found is sent onwards.
3. The primary detector, normally a language model, is asked for people and places. If it is
   cooling down after a failure, or fails now, the fallback is asked instead.
4. If a detector for names was configured and none could answer, ``RedactionUnavailable`` is
   raised. The record is not written with patterns alone under a name that implies more.

The instrument on each result names what ran: the patterns, and which name detector, marked as
the fallback when it was one.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Iterable, Sequence
from typing import Protocol

from agentic_base.redaction.llm import LOCATION, PERSON, DetectorUnavailable
from agentic_base.redaction.patterns import PATTERN_ENTITIES, PatternDetector
from agentic_base.redaction.redact import (
    Redacted,
    RedactionUnavailable,
    Span,
    replace_spans,
)

logger = logging.getLogger(__name__)

DEFAULT_ENTITIES: tuple[str, ...] = (*PATTERN_ENTITIES, PERSON, LOCATION)
_MASK = "#"


class NameDetector(Protocol):
    name: str

    @property
    def instrument(self) -> str: ...

    def available(self) -> bool: ...

    def detect(self, text: str) -> list[Span]: ...


class LayeredRedactor:
    """The redactor the service runs."""

    def __init__(
        self,
        *,
        primary: NameDetector | None = None,
        fallback: NameDetector | None = None,
        entities: Sequence[str] = DEFAULT_ENTITIES,
        allow_list: Iterable[str] = (),
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.entities = frozenset(entities)
        self.allow_list = frozenset(
            term.strip().casefold() for term in allow_list if term.strip()
        )
        self._patterns = PatternDetector()
        self._base = f"agentic-base {_version()} patterns"

    @property
    def instrument(self) -> str:
        detectors = [
            d.instrument for d in (self.primary, self.fallback) if d is not None
        ]
        if not detectors:
            return f"{self._base}, no names or places"
        return f"{self._base} + " + " else ".join(detectors)

    def patterns_only(self) -> LayeredRedactor:
        return LayeredRedactor(
            entities=tuple(self.entities), allow_list=self.allow_list
        )

    def redact(self, text: str) -> Redacted:
        pattern_spans = self._patterns.detect(text) if text.strip() else []
        detectors = [d for d in (self.primary, self.fallback) if d is not None]
        if not detectors:
            return self._finish(
                text, pattern_spans, f"{self._base}, no names or places"
            )
        if not text.strip():
            return Redacted(
                text=text, instrument=f"{self._base} + {detectors[0].instrument}"
            )

        masked = _mask(text, pattern_spans)
        failures: list[str] = []
        for detector in detectors:
            if not detector.available():
                failures.append(f"{detector.name} is cooling down after a failure")
                continue
            try:
                names = detector.detect(masked)
            except DetectorUnavailable as exc:
                failures.append(f"{detector.name}: {exc}")
                logger.warning(
                    "redaction detector %s unavailable: %s", detector.name, exc
                )
                continue
            role = " (fallback)" if detector is not detectors[0] else ""
            return self._finish(
                text,
                pattern_spans + names,
                f"{self._base} + {detector.instrument}{role}",
            )
        raise RedactionUnavailable(
            "no detector for names and places could run: " + "; ".join(failures)
        )

    def _finish(self, text: str, spans: list[Span], instrument: str) -> Redacted:
        kept = [
            s
            for s in spans
            if s.entity in self.entities
            and text[s.start : s.end].strip().casefold() not in self.allow_list
        ]
        return replace_spans(text, kept, instrument)


def _mask(text: str, spans: Sequence[Span]) -> str:
    chars = list(text)
    for s in spans:
        chars[s.start : s.end] = _MASK * (s.end - s.start)
    return "".join(chars)


def _version() -> str:
    try:
        return importlib.metadata.version("surf-agentic-base")
    except importlib.metadata.PackageNotFoundError:
        return "unreleased"
