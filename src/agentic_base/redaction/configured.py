"""The redactor the service applies on write, built once from settings."""

from __future__ import annotations

from functools import cache

from agentic_base.config import Settings, get_settings
from agentic_base.redaction.redact import Redactor


def redactor_from_settings(settings: Settings) -> Redactor | None:
    """``None`` when redaction is off. Anything other than ``none`` or ``presidio`` is refused,
    so a typo cannot turn redaction off while the configuration reads as if it were on."""
    choice = settings.redaction.strip().lower()
    if choice == "none":
        return None
    if choice != "presidio":
        raise ValueError(
            f"REDACTION must be 'none' or 'presidio', not {settings.redaction!r}"
        )

    from agentic_base.redaction.presidio import DEFAULT_ENTITIES, PresidioRedactor

    return PresidioRedactor(
        gliner_model=settings.redaction_gliner_model,
        gliner_revision=settings.redaction_gliner_revision,
        spacy_models=_pairs(settings.redaction_spacy_models),
        entities=_items(settings.redaction_entities) or DEFAULT_ENTITIES,
        allow_list=_items(settings.redaction_allow_list),
    )


@cache
def get_redactor() -> Redactor | None:
    """The configured redactor. Built on first use and kept: loading a model takes seconds."""
    return redactor_from_settings(get_settings())


def _items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _pairs(value: str) -> dict[str, str]:
    pairs = {}
    for item in _items(value):
        language, sep, model = item.partition("=")
        if not sep or not language.strip() or not model.strip():
            raise ValueError(
                f"REDACTION_SPACY_MODELS entries are language=model, not {item!r}"
            )
        pairs[language.strip()] = model.strip()
    return pairs
