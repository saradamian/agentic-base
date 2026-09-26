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


def test_every_transcript_string_is_redacted_and_structure_is_kept() -> None:
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
    assert call["function"] == {"name": "<X>_tool", "arguments": '{"q": "<X>"}'}
    assert out.messages[3] == {
        "role": "tool",
        "name": "<X>_tool",
        "content": "<X> output",
    }


def test_names_tool_inputs_nested_fields_and_extra_are_reached() -> None:
    """A key allow-list misses structure; what decides is where a string sits, not its key."""
    record = _record(
        messages=[
            {"role": "user", "name": "secret sender", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "send_mail",
                        "input": {"to": "a secret address"},
                    }
                ],
            },
            {
                "role": "tool",
                "content": "ok",
                "tool_call_id": "t1",
                "metadata": {"stdout": "a secret line"},
            },
        ],
        extra={"contact": "another secret address"},
    )

    out = redact_run(record, _Upper())

    assert out.messages[0]["name"] == "<X> sender"
    assert out.messages[1]["content"][0]["input"] == {"to": "a <X> address"}
    assert out.messages[2]["metadata"] == {"stdout": "a <X> line"}
    assert out.extra["contact"] == "another <X> address"


def test_roles_part_types_and_tool_call_ids_are_left_for_the_joins() -> None:
    """These strings tie a tool call to its result and select code paths; replacing them
    would break the transcript they hold together."""
    record = _record(
        messages=[
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "secret-1", "input": {}}],
            },
            {"role": "tool", "tool_call_id": "secret-1", "content": "ok"},
        ]
    )

    out = redact_run(record, _Upper())

    assert out.messages[0]["content"][0]["id"] == "secret-1"
    assert out.messages[0]["content"][0]["type"] == "tool_use"
    assert out.messages[1]["tool_call_id"] == "secret-1"
    assert out.messages[1]["role"] == "tool"


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
        "redaction": {
            "examined": 2,
            "found": {"SECRET": 2},
            "instruments": {"upper 1.0 (test)": 2},
            "writer": "none",
        },
    }


def test_a_record_names_every_instrument_that_ran_when_a_fallback_took_over() -> None:
    class _Switching(_Upper):
        def redact(self, text: str) -> Redacted:
            done = super().redact(text)
            ran = "fallback 2.0" if "late" in text else "primary 1.0"
            return Redacted(done.text, done.found, ran)

    record = _record(
        system_prompt="early", messages=[{"role": "user", "content": "late"}]
    )

    out = redact_run(record, _Switching())

    assert out.redaction == "fallback 2.0 | primary 1.0"
    assert out.extra["redaction"]["instruments"] == {
        "fallback 2.0": 1,
        "primary 1.0": 1,
    }


def test_zero_findings_still_reports_how_much_was_examined() -> None:
    out = redact_run(_record(messages=[{"role": "user", "content": "clean"}]), _Upper())

    assert out.extra["redaction"] == {
        "examined": 1,
        "found": {},
        "instruments": {"upper 1.0 (test)": 1},
        "writer": "none",
    }
    assert out.redaction == "upper 1.0 (test)"


def test_the_writers_claim_is_kept_and_does_not_stop_the_redactor() -> None:
    """The claim is the writer's to make; whether the server redacts is not."""
    redactor = _Upper()
    record = _record(
        messages=[{"role": "user", "content": "secret"}], redaction="their tool 2.0"
    )

    out = redact_run(record, redactor)

    assert out.messages[0]["content"] == "<X>"
    assert out.redaction == "upper 1.0 (test)"
    assert out.extra["redaction"]["writer"] == "their tool 2.0"
    assert redactor.seen == ["secret"]
