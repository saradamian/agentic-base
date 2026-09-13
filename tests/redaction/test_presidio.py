"""Presidio as the instrument, in the mode CI can run: patterns only."""

from __future__ import annotations

import importlib.util

import pytest

presidio = pytest.importorskip("agentic_base.redaction.presidio", exc_type=ImportError)
PresidioRedactor = presidio.PresidioRedactor
BsnRecognizer = presidio.BsnRecognizer


@pytest.fixture(scope="module")
def patterns():
    return PresidioRedactor()


def test_contact_bank_and_citizen_numbers_are_redacted(patterns) -> None:
    text = (
        "Mail maria.jansen@example.org, call +31 6 1234 5678, "
        "IBAN NL91ABNA0417164300, BSN 123456782."
    )

    out = patterns.redact(text)

    for value in (
        "maria.jansen@example.org",
        "+31 6 1234 5678",
        "NL91ABNA0417164300",
        "123456782",
    ):
        assert value not in out.text
    assert out.found == {
        "EMAIL_ADDRESS": 1,
        "PHONE_NUMBER": 1,
        "IBAN_CODE": 1,
        "NL_BSN": 1,
    }


def test_job_ids_and_token_counts_are_not_mistaken_for_identifiers(patterns) -> None:
    """Presidio's US and UK recognizers fire on these; the default entity list leaves them out."""
    text = "The job 12345678 failed after 7200 seconds; max_model_len is 262144."

    out = patterns.redact(text)

    assert out.text == text
    assert out.found == {}


def test_the_instrument_says_names_were_not_looked_for(patterns) -> None:
    assert "patterns only, no names or places" in patterns.instrument
    assert patterns.instrument.startswith("presidio-analyzer ")


def test_a_name_passes_through_without_a_model(patterns) -> None:
    """The reason the instrument string says what it says."""
    assert "Maria Jansen" in patterns.redact("Forward it to Maria Jansen.").text


@pytest.mark.parametrize(
    ("number", "valid"),
    [
        ("123456782", True),
        ("111222333", True),
        ("1234.56.782", True),
        ("123456783", False),
        ("000000000", False),
    ],
)
def test_a_bsn_is_recognised_only_when_it_passes_the_eleven_test(number, valid) -> None:
    assert BsnRecognizer().validate_result(number) is valid


def test_an_allow_listed_term_is_kept(patterns) -> None:
    allowed = PresidioRedactor(allow_list=["servicedesk@example.org"])

    text = "Write to servicedesk@example.org or maria.jansen@example.org."

    assert (
        allowed.redact(text).text
        == "Write to servicedesk@example.org or <EMAIL_ADDRESS>."
    )
    assert "allow-list 1 terms" in allowed.instrument


def test_a_spacy_model_that_is_not_installed_is_refused_by_name() -> None:
    """Presidio would otherwise try to download it in the middle of a request."""
    with pytest.raises(ImportError, match="xx_not_a_model"):
        PresidioRedactor(spacy_models={"xx": "xx_not_a_model"})


def test_gliner_without_its_package_is_refused_by_name(monkeypatch) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "gliner" else real(name, *a),
    )

    with pytest.raises(ImportError, match="pip install gliner"):
        PresidioRedactor(gliner_model="urchade/gliner_multi_pii-v1")


def test_the_instrument_names_the_model_and_its_revision(monkeypatch) -> None:
    monkeypatch.setattr(
        presidio, "_gliner_engine", lambda model, revision: presidio._pattern_engine()
    )

    pinned = PresidioRedactor(gliner_model="org/model", gliner_revision="abc123")
    unpinned = PresidioRedactor(gliner_model="org/model")

    assert "ner=gliner org/model@abc123" in pinned.instrument
    assert "ner=gliner org/model@unpinned" in unpinned.instrument


class _Finding:
    def __init__(self, start, end, entity, score):
        self.start, self.end, self.entity_type, self.score = start, end, entity, score


def test_overlapping_findings_become_one_span_labelled_by_the_most_confident() -> None:
    text = "Bel Anouk de Graaf nu"
    findings = [
        _Finding(0, 18, "PERSON", 0.6),
        _Finding(4, 18, "PERSON", 0.85),
        _Finding(15, 21, "LOCATION", 0.4),
    ]

    out = presidio._replace(text, findings)

    assert out.text == "<PERSON>"
    assert out.found == {"PERSON": 1}


def test_separate_findings_are_replaced_independently_and_counted() -> None:
    text = "a@example.org and b@example.org"
    findings = [
        _Finding(18, 31, "EMAIL_ADDRESS", 1.0),
        _Finding(0, 13, "EMAIL_ADDRESS", 1.0),
    ]

    out = presidio._replace(text, findings)

    assert out.text == "<EMAIL_ADDRESS> and <EMAIL_ADDRESS>"
    assert out.found == {"EMAIL_ADDRESS": 2}
