"""Presidio as the redaction instrument.

Without a model, Presidio runs pattern recognizers only: email, phone, IBAN, card numbers, IP
addresses. Names and places, most of the personal data in a transcript, need a model. Two are
supported, and the instrument string on the record names the mode, the model and its revision,
so a pattern-only run is never read as one that removed names.

- GLiNER, one multilingual model for mixed Dutch and English transcripts. Recommended.
- spaCy, one model per language. Faster, but each model mis-tags the other language's ordinary
  words as names, and running both merges both sets of errors.

Neither model is a dependency of the extra: torch alone is over a gigabyte, and spaCy's models
are not on PyPI. The deployer installs what is configured, and a missing model is refused here
by name rather than downloaded in the middle of a request, which Presidio would otherwise try.
``scripts/measure_redaction.py`` runs the three modes on a hand-written sample.

A site's own vocabulary, cluster and partition names above all, is tagged as a location by both
models. ``allow_list`` exempts it; the list is deployment configuration, not code.

The entity list is explicit. Presidio's defaults include US and UK identifiers that fire on job
ids and token counts, and dates, organisations and nationality groups that fire on "Friday",
"7200 seconds" and the name of a cluster. None of those is personal data in an agent
transcript, and redacting them makes the record useless for the thing it is kept for. Dates of
birth are therefore not caught by default; a deployment whose transcripts carry them adds
``DATE_TIME`` and accepts the cost.

One recognizer is added, through Presidio's documented extension point: the Dutch citizen
service number, validated by the eleven test. Presidio ships none, and it is the identifier a
Dutch health use case turns on.

Presidio's anonymizer is not used. It pins ``cryptography`` below 49 for an encryption operator
this adapter never calls, and a single lock for every extra would hold the service on a release
with six published advisories. Replacing a found span with its entity type is all that is needed
from it, and ``_replace`` does that.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from agentic_base.redaction.redact import Redacted

try:
    from presidio_analyzer import (
        AnalyzerEngine,
        Pattern,
        PatternRecognizer,
        RecognizerRegistry,
    )
    from presidio_analyzer.nlp_engine import NlpEngineProvider, NoOpNlpEngine
    from presidio_analyzer.predefined_recognizers import SpacyRecognizer
except ImportError as exc:
    raise ImportError(
        "agentic_base.redaction.presidio needs the redaction extra: "
        "pip install 'surf-agentic-base[redaction]'"
    ) from exc

BSN_ENTITY = "NL_BSN"

#: What is redacted unless a deployment says otherwise. People, places, contact details, bank
#: and card numbers, addresses on a network, and the Dutch citizen service number.
DEFAULT_ENTITIES: tuple[str, ...] = (
    "PERSON",
    "LOCATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IBAN_CODE",
    "CREDIT_CARD",
    "IP_ADDRESS",
    BSN_ENTITY,
)

#: Pattern recognizers are defined for English in Presidio and are language-neutral in practice.
_PATTERN_LANGUAGE = "en"


class BsnRecognizer(PatternRecognizer):
    """A nine-digit number that passes the eleven test, optionally grouped by dots or spaces."""

    def __init__(self, supported_language: str = _PATTERN_LANGUAGE) -> None:
        super().__init__(
            supported_entity=BSN_ENTITY,
            patterns=[Pattern("bsn", r"\b\d{4}[ .]?\d{2}[ .]?\d{3}\b", 0.4)],
            context=[
                "bsn",
                "burgerservicenummer",
                "sofinummer",
                "citizen service number",
            ],
            supported_language=supported_language,
        )

    def validate_result(self, pattern_text: str) -> bool:
        digits = [int(c) for c in pattern_text if c.isdigit()]
        if len(digits) != 9 or sum(digits) == 0:
            return False
        total = (
            sum(d * w for d, w in zip(digits[:8], range(9, 1, -1), strict=True))
            - digits[8]
        )
        return total % 11 == 0


class PresidioRedactor:
    """Redact text with Presidio's analyzer and anonymizer.

    ``gliner_model`` names a GLiNER PII model on the Hugging Face hub, pinned by
    ``gliner_revision``. ``spacy_models`` maps a language code to an installed spaCy model. Both
    may be given; with neither, patterns only.
    """

    def __init__(
        self,
        *,
        gliner_model: str = "",
        gliner_revision: str = "",
        spacy_models: Mapping[str, str] | None = None,
        entities: Sequence[str] = DEFAULT_ENTITIES,
        allow_list: Sequence[str] = (),
    ) -> None:
        self.entities = list(entities)
        self.allow_list = list(allow_list)
        spacy_models = dict(spacy_models or {})
        self._engines = [_pattern_engine()]
        modes = []
        if gliner_model:
            self._engines.append(_gliner_engine(gliner_model, gliner_revision))
            modes.append(f"gliner {gliner_model}@{gliner_revision or 'unpinned'}")
        for language, model in spacy_models.items():
            self._engines.append(_spacy_engine(language, model))
            modes.append(f"spacy {model} {_version(model)}")
        mode = (
            "ner=" + ", ".join(modes) if modes else "patterns only, no names or places"
        )
        allowed = (
            f"; allow-list {len(self.allow_list)} terms" if self.allow_list else ""
        )
        self._instrument = (
            f"presidio-analyzer {_version('presidio-analyzer')} "
            f"({mode}; entities={','.join(self.entities)}{allowed})"
        )

    @property
    def instrument(self) -> str:
        return self._instrument

    def redact(self, text: str) -> Redacted:
        if not text.strip():
            return Redacted(text=text)
        results: list[Any] = []
        for engine, language in self._engines:
            results += engine.analyze(
                text=text,
                language=language,
                entities=self.entities,
                allow_list=self.allow_list or None,
            )
        return _replace(text, results)


def _replace(text: str, results: Sequence[Any]) -> Redacted:
    """Replace every found span with ``<ENTITY_TYPE>``.

    Findings from several engines overlap. Overlapping findings become one span covering all of
    them, labelled by the most confident, and on a tie the longest; a partial overlap therefore
    removes the union, which errs towards removing too much rather than leaving half a name.
    """
    spans: list[list[Any]] = []
    for r in sorted(results, key=lambda r: (r.start, -r.end)):
        if spans and r.start < spans[-1][1]:
            current = spans[-1]
            current[1] = max(current[1], r.end)
            if (r.score, r.end - r.start) > (current[3], current[4]):
                current[2], current[3], current[4] = (
                    r.entity_type,
                    r.score,
                    r.end - r.start,
                )
        else:
            spans.append([r.start, r.end, r.entity_type, r.score, r.end - r.start])
    out = text
    for start, end, entity, _, _ in reversed(spans):
        out = out[:start] + f"<{entity}>" + out[end:]
    return Redacted(text=out, found=dict(Counter(span[2] for span in spans)))


def _pattern_engine() -> tuple[Any, str]:
    nlp = NoOpNlpEngine(models=[{"lang_code": _PATTERN_LANGUAGE, "model_name": "none"}])
    nlp.load()
    registry = RecognizerRegistry(supported_languages=[_PATTERN_LANGUAGE])
    registry.load_predefined_recognizers(languages=[_PATTERN_LANGUAGE], nlp_engine=nlp)
    registry.add_recognizer(BsnRecognizer())
    engine = AnalyzerEngine(
        nlp_engine=nlp, registry=registry, supported_languages=[_PATTERN_LANGUAGE]
    )
    return engine, _PATTERN_LANGUAGE


def _gliner_engine(model: str, revision: str) -> tuple[Any, str]:
    if importlib.util.find_spec("gliner") is None:
        raise ImportError(
            f"redaction with GLiNER model {model} needs the gliner package: pip install gliner"
        )
    from presidio_analyzer.predefined_recognizers import GLiNERRecognizer

    nlp = NoOpNlpEngine(models=[{"lang_code": _PATTERN_LANGUAGE, "model_name": "none"}])
    nlp.load()
    registry = RecognizerRegistry(supported_languages=[_PATTERN_LANGUAGE])
    kwargs = {"revision": revision} if revision else {}
    registry.add_recognizer(
        GLiNERRecognizer(
            supported_language=_PATTERN_LANGUAGE,
            model_name=model,
            entity_mapping=_GLINER_ENTITIES,
            **kwargs,
        )
    )
    engine = AnalyzerEngine(
        nlp_engine=nlp, registry=registry, supported_languages=[_PATTERN_LANGUAGE]
    )
    return engine, _PATTERN_LANGUAGE


def _spacy_engine(language: str, model: str) -> tuple[Any, str]:
    if importlib.util.find_spec(model) is None:
        raise ImportError(
            f"redaction for language {language} needs the spaCy model {model} installed; "
            "it is not on PyPI, see spaCy's model releases"
        )
    nlp = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": language, "model_name": model}],
        }
    ).create_engine()
    registry = RecognizerRegistry(supported_languages=[language])
    registry.add_recognizer(SpacyRecognizer(supported_language=language))
    engine = AnalyzerEngine(
        nlp_engine=nlp, registry=registry, supported_languages=[language]
    )
    return engine, language


#: GLiNER takes labels as free text. These are the ones its PII models are trained on for the
#: entity types this adapter redacts by default.
_GLINER_ENTITIES = {"person": "PERSON", "location": "LOCATION", "address": "LOCATION"}


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
