"""Behaviour of the endpoint probe.

These tests exist because the obvious version of this check was wrong in a way that mattered.
It called any non-5xx response healthy, so a refused credential and a wrong path both reported
healthy, and those are the two misconfigurations that actually occur. The first three tests
below are the ones that would have caught it.
"""

from app.llm.health import EndpointState, interpret_response


def _completion(content: str | None = "hi") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_a_refused_credential_is_not_healthy() -> None:
    result = interpret_response(401, {"error": "key does not exist"}, "some-model")

    assert result.state is EndpointState.UNAUTHORISED
    assert not result.usable


def test_a_forbidden_response_is_not_healthy() -> None:
    assert interpret_response(403, {}, "m").state is EndpointState.UNAUTHORISED


def test_a_wrong_path_or_absent_model_is_not_healthy() -> None:
    result = interpret_response(404, {}, "missing-model")

    assert result.state is EndpointState.MODEL_NOT_SERVED
    assert not result.usable


def test_a_server_error_reports_the_endpoint_as_unreachable() -> None:
    assert interpret_response(503, {}, "m").state is EndpointState.UNREACHABLE


def test_a_successful_completion_is_healthy() -> None:
    result = interpret_response(200, _completion(), "m")

    assert result.state is EndpointState.OK
    assert result.usable


def test_a_response_with_no_choices_is_not_healthy() -> None:
    assert interpret_response(200, {}, "m").state is EndpointState.COMPLETION_FAILED


def test_a_completion_with_no_content_is_not_healthy() -> None:
    """A model that returns only reasoning tokens has answered without answering."""
    result = interpret_response(200, _completion(content=None), "m")

    assert result.state is EndpointState.COMPLETION_FAILED


def test_a_tool_call_with_no_content_counts_as_an_answer() -> None:
    body: dict[str, object] = {
        "choices": [
            {"message": {"role": "assistant", "content": None, "tool_calls": [{}]}}
        ]
    }

    assert interpret_response(200, body, "m").state is EndpointState.OK


def test_an_unexpected_client_error_is_reported_with_its_detail() -> None:
    result = interpret_response(422, {"error": "max_tokens too large"}, "m")

    assert result.state is EndpointState.COMPLETION_FAILED
    assert "max_tokens" in result.detail
