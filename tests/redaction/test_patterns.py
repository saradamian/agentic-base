"""The pattern layer: what it finds, what it must leave alone, and the checksums behind it."""

from __future__ import annotations

import pytest

from agentic_base.redaction.patterns import (
    PatternDetector,
    bsn_is_valid,
    iban_is_valid,
    luhn_is_valid,
)
from agentic_base.redaction.redact import replace_spans


def _redact(text: str) -> str:
    return replace_spans(text, PatternDetector().detect(text)).text


# Credentials are assembled at run time so no literal in this file has a real token's shape.
_GITHUB = "gh" + "p_" + "a1B2" * 9
_GITLAB = "glp" + "at-" + "x" * 20
_HF = "h" + "f_" + "Q" * 34
_WILLMA = "77696c6c6d61" + "-0123abcd-0aec-4df0-93f0-" + "0123456789ab"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mail maria.jansen@example.org now.", "Mail <EMAIL_ADDRESS> now."),
        (
            "Call +31 6 1234 5678, 020-7654321 or 06 12345678.",
            "Call <PHONE_NUMBER>, <PHONE_NUMBER> or <PHONE_NUMBER>.",
        ),
        (
            "IBAN NL91ABNA0417164300 or NL91 ABNA 0417 1643 00.",
            "IBAN <IBAN_CODE> or <IBAN_CODE>.",
        ),
        ("Card 4111 1111 1111 1111.", "Card <CREDIT_CARD>."),
        ("BSN 123456782 and 1234.56.782.", "BSN <NL_BSN> and <NL_BSN>."),
        ("Hosts 192.0.2.10 and 2001:db8::1.", "Hosts <IP_ADDRESS> and <IP_ADDRESS>."),
        (f"export GITHUB_TOKEN={_GITHUB}", "export GITHUB_TOKEN=<CREDENTIAL>"),
        (
            f"git clone https://oauth2:{_GITLAB}@host/repo",
            "git clone https://oauth2:<CREDENTIAL>@host/repo",
        ),
        (
            f"HF_TOKEN {_HF} and key {_WILLMA}",
            "HF_TOKEN <CREDENTIAL> and key <CREDENTIAL>",
        ),
        ("Authorization: Bearer " + "t" * 32, "Authorization: Bearer <CREDENTIAL>"),
        ('password = "hunter22secret"', 'password = "<CREDENTIAL>"'),
    ],
)
def test_each_identifier_is_replaced_by_its_type(text, expected) -> None:
    assert _redact(text) == expected


def test_a_private_key_block_is_removed_whole() -> None:
    header, footer = (
        "-----BEGIN OPENSSH PRIVATE" + " KEY-----",
        "-----END OPENSSH PRIVATE" + " KEY-----",
    )
    text = f"cat id_ed25519\n{header}\nb3BlbnNzaC1rZXk\nAAAAB3NzaC1\n{footer}\ndone"

    assert _redact(text) == "cat id_ed25519\n<CREDENTIAL>\ndone"


@pytest.mark.parametrize(
    "text",
    [
        "The job 12345678 failed after 7200 seconds on partition gpu_h100.",
        "max_model_len 262144, epoch 1777386525123, Python 3.10.12, version 1.2.3",
        "commit 1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d at 12:30:45",
        "token = self.token and the session_id is 42",
    ],
)
def test_numbers_hashes_and_versions_in_an_agent_transcript_are_left_alone(
    text,
) -> None:
    assert _redact(text) == text


def test_the_willma_key_shape_has_six_groups() -> None:
    """agentic-env's corpus scanner had one UUID group too few and matched no real key."""
    five_groups = "77696c6c6d61-0123abcd-0aec-4df0-0123456789ab"

    assert _redact(f"key {_WILLMA}") == "key <CREDENTIAL>"
    assert _redact(f"key {five_groups}") == f"key {five_groups}"


def test_an_overlap_is_named_by_the_more_specific_shape() -> None:
    """The digit groups inside an IBAN also look like a phone number."""
    found = PatternDetector().detect("NL91 ABNA 0417 1643 00")

    assert replace_spans("NL91 ABNA 0417 1643 00", found).found == {"IBAN_CODE": 1}


@pytest.mark.parametrize(
    ("check", "valid", "invalid"),
    [
        (iban_is_valid, "NL91ABNA0417164300", "NL91ABNA0417164301"),
        (luhn_is_valid, "4111111111111111", "4111111111111112"),
        (bsn_is_valid, "123456782", "123456783"),
    ],
)
def test_a_checksum_decides(check, valid, invalid) -> None:
    assert check(valid) is True
    assert check(invalid) is False


def test_a_card_number_must_start_like_a_card() -> None:
    """A millisecond timestamp is thirteen digits and passes Luhn one time in ten."""
    assert luhn_is_valid("1777386525123") is False
