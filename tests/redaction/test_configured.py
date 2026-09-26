"""Building the service's redactor from settings."""

from __future__ import annotations

import pytest

from agentic_base.config import Settings
from agentic_base.redaction.configured import redactor_from_settings
from agentic_base.redaction.layered import LayeredRedactor
from agentic_base.redaction.llm import LlmDetector


def test_redaction_is_off_unless_configured() -> None:
    assert redactor_from_settings(Settings()) is None


def test_a_misspelled_mode_is_refused_rather_than_read_as_off() -> None:
    with pytest.raises(ValueError, match="none, patterns, names"):
        redactor_from_settings(Settings(redaction="name"))


def test_an_entity_type_no_detector_produces_fails_the_start() -> None:
    """`EMAIL` is a plausible spelling of `EMAIL_ADDRESS`; accepted, it would keep nothing
    while the configuration read as on."""
    with pytest.raises(ValueError, match="EMAIL, IBAN, PHONE"):
        redactor_from_settings(
            Settings(redaction="patterns", redaction_entities="EMAIL,PHONE,IBAN")
        )


def test_a_known_entity_type_narrows_what_is_removed() -> None:
    redactor = redactor_from_settings(
        Settings(redaction="patterns", redaction_entities="EMAIL_ADDRESS")
    )

    assert isinstance(redactor, LayeredRedactor)
    assert redactor.entities == frozenset({"EMAIL_ADDRESS"})


def test_patterns_mode_runs_no_name_detector() -> None:
    redactor = redactor_from_settings(
        Settings(redaction="patterns", redaction_allow_list="Snellius, LUMI")
    )

    assert isinstance(redactor, LayeredRedactor) and redactor.primary is None
    assert redactor.allow_list == frozenset({"snellius", "lumi"})


def test_names_mode_needs_a_detector() -> None:
    with pytest.raises(ValueError, match="REDACTION_LLM_URL"):
        redactor_from_settings(Settings(redaction="names"))


def test_names_mode_with_an_endpoint_uses_the_model_as_primary() -> None:
    redactor = redactor_from_settings(
        Settings(
            redaction="names",
            redaction_llm_url="https://llm.example/v1",
            redaction_llm_api_key="k",
            redaction_llm_model="m",
            redaction_llm_timeout_s=280,
        )
    )

    assert isinstance(redactor, LayeredRedactor) and isinstance(
        redactor.primary, LlmDetector
    )
    assert redactor.fallback is None


def test_an_endpoint_without_a_key_is_refused() -> None:
    with pytest.raises(ValueError, match="API key"):
        redactor_from_settings(
            Settings(
                redaction="names",
                redaction_llm_url="https://llm.example/v1",
                redaction_llm_model="m",
            )
        )


def test_the_api_key_is_not_shown_when_settings_are_logged() -> None:
    settings = Settings(redaction_llm_api_key="k-secret-123")

    assert "k-secret-123" not in str(settings.model_dump())
