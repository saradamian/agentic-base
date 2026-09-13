"""The redactor the service applies on write, built once from settings."""

from __future__ import annotations

from functools import cache

from agentic_base.config import Settings, get_settings
from agentic_base.redaction.layered import (
    DEFAULT_ENTITIES,
    LayeredRedactor,
    NameDetector,
)
from agentic_base.redaction.redact import Redactor

MODES = ("none", "patterns", "names")


def redactor_from_settings(settings: Settings) -> Redactor | None:
    """``None`` when redaction is off.

    ``patterns`` runs the pattern layer only. ``names`` adds a language model and, or, a GLiNER
    fallback, and at least one of them must be configured. Anything else is refused, so a typo
    cannot turn redaction off while the configuration reads as if it were on.
    """
    mode = settings.redaction.strip().lower()
    if mode not in MODES:
        raise ValueError(
            f"REDACTION must be one of {', '.join(MODES)}, not {settings.redaction!r}"
        )
    if mode == "none":
        return None

    entities = _items(settings.redaction_entities) or DEFAULT_ENTITIES
    allow_list = _items(settings.redaction_allow_list)
    if mode == "patterns":
        return LayeredRedactor(entities=entities, allow_list=allow_list)

    primary: NameDetector | None = None
    fallback: NameDetector | None = None
    if settings.redaction_llm_url or settings.redaction_llm_model:
        from agentic_base.redaction.llm import LlmDetector

        primary = LlmDetector(
            base_url=settings.redaction_llm_url,
            api_key=settings.redaction_llm_api_key.get_secret_value(),
            model=settings.redaction_llm_model,
            timeout_s=settings.redaction_llm_timeout_s,
            chunk_words=settings.redaction_llm_chunk_words,
            concurrency=settings.redaction_llm_concurrency,
            cooldown_s=settings.redaction_llm_cooldown_s,
        )
    if settings.redaction_gliner_model:
        from agentic_base.redaction.gliner import GlinerDetector

        fallback = GlinerDetector(
            model=settings.redaction_gliner_model,
            revision=settings.redaction_gliner_revision,
            device=settings.redaction_gliner_device,
        )
    if primary is None and fallback is None:
        raise ValueError(
            "REDACTION=names needs REDACTION_LLM_URL and REDACTION_LLM_MODEL, "
            "or REDACTION_GLINER_MODEL, or both"
        )
    if primary is None:
        primary, fallback = fallback, None
    return LayeredRedactor(
        primary=primary, fallback=fallback, entities=entities, allow_list=allow_list
    )


@cache
def get_redactor() -> Redactor | None:
    """The configured redactor. Built on first use and kept: loading a model takes seconds."""
    return redactor_from_settings(get_settings())


def _items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
