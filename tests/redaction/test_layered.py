"""Patterns always, names from the primary, the fallback when it cannot, and closed when neither can."""

from __future__ import annotations

import pytest

from agentic_base.redaction.layered import LayeredRedactor
from agentic_base.redaction.llm import DetectorUnavailable
from agentic_base.redaction.redact import RedactionUnavailable, Span


class _Names:
    def __init__(
        self, name: str, words=("Maria",), fail: bool = False, cooling: bool = False
    ) -> None:
        self.name, self.words, self.fail, self.cooling = name, words, fail, cooling
        self.seen: list[str] = []

    @property
    def instrument(self) -> str:
        return f"{self.name} 1.0"

    def available(self) -> bool:
        return not self.cooling

    def detect(self, text: str) -> list[Span]:
        self.seen.append(text)
        if self.fail:
            raise DetectorUnavailable("down")
        return [
            Span(text.find(w), text.find(w) + len(w), "PERSON")
            for w in self.words
            if w in text
        ]


TEXT = "Mail Maria at maria@example.org, token hf_" + "Q" * 34


def test_patterns_are_masked_before_the_name_detector_sees_the_text() -> None:
    primary = _Names("llm")

    out = LayeredRedactor(primary=primary).redact(TEXT)

    assert out.text == "Mail <PERSON> at <EMAIL_ADDRESS>, token <CREDENTIAL>"
    assert "maria@example.org" not in primary.seen[0] and "hf_" not in primary.seen[0]
    assert len(primary.seen[0]) == len(TEXT)
    assert out.instrument.endswith("+ llm 1.0")


def test_the_fallback_runs_when_the_primary_fails_and_the_record_says_so() -> None:
    primary, fallback = _Names("llm", fail=True), _Names("gliner")

    out = LayeredRedactor(primary=primary, fallback=fallback).redact(TEXT)

    assert "<PERSON>" in out.text
    assert out.instrument.endswith("+ gliner 1.0 (fallback)")


def test_a_primary_that_is_cooling_down_is_not_asked() -> None:
    primary, fallback = _Names("llm", cooling=True), _Names("gliner")

    LayeredRedactor(primary=primary, fallback=fallback).redact(TEXT)

    assert primary.seen == [] and len(fallback.seen) == 1


def test_when_no_name_detector_can_run_nothing_is_returned_as_redacted() -> None:
    redactor = LayeredRedactor(
        primary=_Names("llm", fail=True), fallback=_Names("gliner", fail=True)
    )

    with pytest.raises(RedactionUnavailable, match="llm: down; gliner: down"):
        redactor.redact(TEXT)


def test_without_a_name_detector_the_instrument_says_names_were_not_looked_for() -> (
    None
):
    out = LayeredRedactor().redact(TEXT)

    assert "Maria" in out.text and "<EMAIL_ADDRESS>" in out.text
    assert out.instrument.endswith("patterns, no names or places")


def test_patterns_only_keeps_the_allow_list_and_entities() -> None:
    redactor = LayeredRedactor(
        primary=_Names("llm", fail=True), entities=("EMAIL_ADDRESS",), allow_list=["x"]
    )

    only = redactor.patterns_only()

    assert (
        only.primary is None
        and only.entities == redactor.entities
        and only.allow_list == redactor.allow_list
    )


def test_an_allow_listed_term_and_an_unlisted_entity_are_kept() -> None:
    redactor = LayeredRedactor(
        primary=_Names("llm", words=("Maria", "Snellius")),
        entities=("PERSON", "CREDENTIAL"),
        allow_list=["snellius"],
    )

    out = redactor.redact("Maria ran it on Snellius; mail maria@example.org")

    assert out.text == "<PERSON> ran it on Snellius; mail maria@example.org"
