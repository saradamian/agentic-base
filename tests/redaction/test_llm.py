"""The language-model detector, against a fake endpoint."""

from __future__ import annotations

import json

import httpx
import pytest

from agentic_base.redaction.llm import DetectorUnavailable, LlmDetector, _pieces


def _answer(people=(), places=(), finish="stop", content=None) -> dict:
    body = (
        content
        if content is not None
        else json.dumps({"people": list(people), "places": list(places)})
    )
    return {"choices": [{"finish_reason": finish, "message": {"content": body}}]}


class _Endpoint:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": "m", "created": 1777386525}]}
            )
        body = json.loads(request.content)
        self.requests.append(
            {"body": body, "auth": request.headers.get("authorization")}
        )
        return self.handler(body)


def _detector(endpoint, **kwargs) -> LlmDetector:
    now = kwargs.pop("now", [0.0])
    return LlmDetector(
        base_url="https://llm.example/v1",
        api_key="k-123",
        model="m",
        transport=httpx.MockTransport(endpoint),
        clock=lambda: now[0],
        sleep=lambda s: None,
        **kwargs,
    )


def test_names_come_back_as_spans_at_their_offsets_and_the_request_is_constrained() -> (
    None
):
    endpoint = _Endpoint(
        lambda body: httpx.Response(200, json=_answer(["Maria Jansen"], ["Utrecht"]))
    )
    text = "Maria Jansen lives in Utrecht; Maria Jansen agreed."

    spans = _detector(endpoint).detect(text)

    assert sorted((text[s.start : s.end], s.entity) for s in spans) == [
        ("Maria Jansen", "PERSON"),
        ("Maria Jansen", "PERSON"),
        ("Utrecht", "LOCATION"),
    ]
    sent = endpoint.requests[0]
    assert sent["auth"] == "Bearer k-123"
    assert sent["body"]["temperature"] == 0
    assert sent["body"]["response_format"]["type"] == "json_schema"
    fence = sent["body"]["messages"][1]["content"].split("\n", 1)[0]
    assert fence.startswith("TEXT-") and fence in sent["body"]["messages"][0]["content"]


def test_an_item_that_is_not_in_the_text_removes_nothing_and_is_counted() -> None:
    endpoint = _Endpoint(
        lambda body: httpx.Response(200, json=_answer(["Emma", "Invented Person"]))
    )
    detector = _detector(endpoint)

    spans = detector.detect("Report back to Emma, not to Emmanuel.")

    assert [(s.start, s.end) for s in spans] == [(15, 19)]
    assert detector.unmatched == 1


def test_long_text_is_split_into_overlapping_pieces_that_cover_every_word() -> None:
    text = " ".join(f"w{i}" for i in range(250))

    pieces = _pieces(text, 100, 10)

    assert pieces[0][0] == 0 and pieces[-1][1] == len(text)
    assert all(a[1] > b[0] for a, b in zip(pieces, pieces[1:], strict=False))


def test_a_truncated_answer_is_split_and_asked_again() -> None:
    def handler(body):
        words = body["messages"][1]["content"].split()
        if len(words) > 150:
            return httpx.Response(200, json=_answer(finish="length"))
        return httpx.Response(200, json=_answer(["Emma"] if "Emma" in words else []))

    text = " ".join(["word"] * 150 + ["Emma"] + ["word"] * 99)
    endpoint = _Endpoint(handler)

    spans = _detector(endpoint, chunk_words=1500, min_chunk_words=100).detect(text)

    assert [text[s.start : s.end] for s in spans] == ["Emma"]
    assert len(endpoint.requests) == 3


def test_an_answer_outside_the_schema_makes_the_detector_unavailable() -> None:
    endpoint = _Endpoint(
        lambda body: httpx.Response(200, json=_answer(content="```json\n{}\n```"))
    )

    with pytest.raises(DetectorUnavailable, match="schema"):
        _detector(endpoint).detect("Mail Maria.")


def test_a_gateway_status_is_retried_once() -> None:
    statuses = iter([503, 200])
    endpoint = _Endpoint(
        lambda body: (
            httpx.Response(s, json=_answer(["Maria"]))
            if (s := next(statuses)) == 200
            else httpx.Response(s)
        )
    )

    spans = _detector(endpoint).detect("Mail Maria.")

    assert len(spans) == 1 and len(endpoint.requests) == 2


def test_a_refused_request_is_not_retried_and_does_not_leak_the_key() -> None:
    endpoint = _Endpoint(
        lambda body: httpx.Response(403, json={"error": "Model usage not allowed."})
    )

    with pytest.raises(DetectorUnavailable) as caught:
        _detector(endpoint).detect("Mail Maria.")

    assert "403" in str(caught.value) and "k-123" not in str(caught.value)
    assert len(endpoint.requests) == 1


def test_a_timeout_is_not_retried() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    detector = LlmDetector(
        base_url="https://llm.example/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(handler),
        timeout_s=300,
    )

    with pytest.raises(DetectorUnavailable, match="300 s"):
        detector.detect("Mail Maria.")
    assert len(calls) == 1


def test_after_a_failure_the_detector_cools_down_then_recovers() -> None:
    now = [100.0]
    healthy = [False]
    endpoint = _Endpoint(
        lambda body: (
            httpx.Response(200, json=_answer(["Maria"]))
            if healthy[0]
            else httpx.Response(500)
        )
    )
    detector = _detector(endpoint, now=now, cooldown_s=60)

    with pytest.raises(DetectorUnavailable):
        detector.detect("Mail Maria.")
    assert detector.available() is False

    now[0] = 161.0
    healthy[0] = True
    assert detector.available() is True
    assert len(detector.detect("Mail Maria.")) == 1


def test_the_instrument_names_the_model_and_its_registration_time_once_known() -> None:
    endpoint = _Endpoint(lambda body: httpx.Response(200, json=_answer()))
    detector = _detector(endpoint)
    assert detector.instrument == "llm m"

    detector.detect("nothing here")

    assert detector.instrument == "llm m, created 1777386525"


@pytest.mark.parametrize("missing", ["base_url", "api_key", "model"])
def test_a_detector_without_an_endpoint_key_or_model_is_refused(missing) -> None:
    kwargs = {"base_url": "https://llm.example/v1", "api_key": "k", "model": "m"}
    kwargs[missing] = ""
    with pytest.raises(ValueError):
        LlmDetector(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
            model=kwargs["model"],
        )
