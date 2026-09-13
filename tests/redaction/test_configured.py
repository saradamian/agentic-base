"""Building the service's redactor from settings."""

from __future__ import annotations

import pytest

from agentic_base.config import Settings
from agentic_base.redaction.configured import _pairs, redactor_from_settings


def test_redaction_is_off_unless_configured() -> None:
    assert redactor_from_settings(Settings()) is None


def test_a_misspelled_choice_is_refused_rather_than_read_as_off() -> None:
    with pytest.raises(ValueError, match="presidio"):
        redactor_from_settings(Settings(redaction="presido"))


def test_presidio_is_built_with_the_configured_allow_list() -> None:
    pytest.importorskip("presidio_analyzer")

    redactor = redactor_from_settings(
        Settings(redaction="presidio", redaction_allow_list="Snellius, LUMI")
    )

    assert redactor is not None
    assert "allow-list 2 terms" in redactor.instrument


def test_spacy_models_are_language_model_pairs() -> None:
    assert _pairs("en=en_core_web_lg, nl=nl_core_news_lg") == {
        "en": "en_core_web_lg",
        "nl": "nl_core_news_lg",
    }
    with pytest.raises(ValueError, match="language=model"):
        _pairs("en_core_web_lg")
