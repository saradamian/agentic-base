"""The redaction seam: what is redacted, what the record says afterwards."""

from __future__ import annotations

from agentic_base.domain.outcomes import RunRecordCreate
from agentic_base.redaction import Redacted, Redactor, redact_run


class _Upper:
    """Replaces the word 'secret' and counts it; enough to see what the seam reaches."""

    instrument = "upper 1.0 (test)"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def redact(self, text: str) -> Redacted:
        self.seen.append(text)
        n = text.count("secret")
        return Redacted(
            text=text.replace("secret", "<X>"), found={"SECRET": n} if n else {}
        )


def _record(**kwargs) -> RunRecordCreate:
    return RunRecordCreate(tenant="t", code_revision="abc", **kwargs)


def test_the_fake_satisfies_the_protocol() -> None:
    assert isinstance(_Upper(), Redactor)


def test_every_transcript_text_is_redacted_and_structure_is_kept() -> None:
    record = _record(
        system_prompt="the secret prompt",
        messages=[
            {"role": "user", "content": "a secret here"},
            {"role": "user", "content": [{"type": "text", "text": "secret part"}]},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "secret-id",
                        "function": {
                            "name": "secret_tool",
                            "arguments": '{"q": "secret"}',
                        },
                    }
                ],
            },
            {"role": "tool", "name": "secret_tool", "content": "secret output"},
        ],
    )

    out = redact_run(record, _Upper())

    assert out.system_prompt == "the <X> prompt"
    assert out.messages[0] == {"role": "user", "content": "a <X> here"}
    assert out.messages[1]["content"] == [{"type": "text", "text": "<X> part"}]
    call = out.messages[2]["tool_calls"][0]
    assert call["id"] == "secret-id"
    assert call["function"] == {"name": "secret_tool", "arguments": '{"q": "<X>"}'}
    assert out.messages[3] == {
        "role": "tool",
        "name": "secret_tool",
        "content": "<X> output",
    }


def test_the_record_names_the_instrument_and_reports_what_it_examined() -> None:
    record = _record(
        system_prompt="nothing here",
        messages=[{"role": "user", "content": "secret and secret"}],
        extra={"kept": 1},
    )

    out = redact_run(record, _Upper())

    assert out.redaction == "upper 1.0 (test)"
    assert out.extra == {
        "kept": 1,
        "redaction": {"examined": 2, "found": {"SECRET": 2}},
    }


def test_zero_findings_still_reports_how_much_was_examined() -> None:
    out = redact_run(_record(messages=[{"role": "user", "content": "clean"}]), _Upper())

    assert out.extra["redaction"] == {"examined": 1, "found": {}}
    assert out.redaction == "upper 1.0 (test)"


def test_a_record_the_writer_already_redacted_is_left_alone() -> None:
    redactor = _Upper()
    record = _record(
        messages=[{"role": "user", "content": "secret"}], redaction="their tool 2.0"
    )

    out = redact_run(record, redactor)

    assert out is record
    assert redactor.seen == []
