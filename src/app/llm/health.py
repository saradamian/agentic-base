"""Pre-flight probe for a model endpoint.

The obvious implementation of this is wrong, and it was wrong in the predecessor project until
it cost two dead CI gates in one day. That version called any non-5xx response healthy, and said
so explicitly about 401. A rejected credential and a wrong path are the two misconfigurations
that actually happen, and both answer with a 4xx. So the check reported healthy for precisely
the cases it existed to catch, and the graceful-skip path in its callers could never fire.

A health check for a serving platform therefore asserts that a trivial completion comes back,
not that a socket answered. It costs a handful of tokens and it is the only result worth acting
on.

The outcome is a named state rather than a boolean, because the operator response differs: a
refused credential is a secret to rotate, an absent model is a serve to start, and a timeout is
capacity.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import httpx

from app.limits import get_limits


class EndpointState(str, enum.Enum):
    OK = "ok"
    UNREACHABLE = "unreachable"
    """Nothing answered. Network, tunnel, or the serve is gone."""

    UNAUTHORISED = "unauthorised"
    """The endpoint answered and refused the credential."""

    MODEL_NOT_SERVED = "model_not_served"
    """The endpoint answered but does not serve the model that was asked for."""

    COMPLETION_FAILED = "completion_failed"
    """The endpoint accepted the request and did not return a usable completion."""

    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ProbeResult:
    state: EndpointState
    detail: str
    model: str = ""

    @property
    def usable(self) -> bool:
        return self.state is EndpointState.OK

    def __str__(self) -> str:
        return f"{self.state.value}: {self.detail}"


def probe_endpoint(
    base_url: str,
    model: str,
    *,
    api_key: str = "",
    timeout_s: float | None = None,
) -> ProbeResult:
    """Ask an OpenAI-compatible endpoint for one token and report what happened.

    Never raises. Every failure is a named state, because a probe that throws gets wrapped in a
    try block and turns into a silent pass.
    """
    timeout = timeout_s if timeout_s is not None else get_limits().llm_probe_timeout_s
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        return ProbeResult(
            EndpointState.TIMEOUT, f"no answer within {timeout}s ({exc!s})", model
        )
    except httpx.HTTPError as exc:
        return ProbeResult(EndpointState.UNREACHABLE, str(exc), model)

    return interpret_response(response.status_code, _safe_json(response), model)


def _safe_json(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {"_text": response.text[:500]}
    return body if isinstance(body, dict) else {"_body": body}


def interpret_response(status_code: int, body: dict, model: str = "") -> ProbeResult:
    """Map an endpoint's answer to a state. Separated so it can be tested without a network."""
    if status_code in (401, 403):
        return ProbeResult(
            EndpointState.UNAUTHORISED, f"credential refused ({status_code})", model
        )
    if status_code == 404:
        return ProbeResult(
            EndpointState.MODEL_NOT_SERVED,
            f"endpoint answered 404; model {model!r} or path is wrong",
            model,
        )
    if status_code >= 500:
        return ProbeResult(
            EndpointState.UNREACHABLE, f"server error {status_code}", model
        )
    if status_code >= 400:
        detail = str(body.get("error") or body.get("_text") or body)[:200]
        return ProbeResult(
            EndpointState.COMPLETION_FAILED, f"{status_code}: {detail}", model
        )

    choices = body.get("choices")
    if not choices:
        return ProbeResult(
            EndpointState.COMPLETION_FAILED, "no choices in the response", model
        )
    message = (choices[0] or {}).get("message") or {}
    if message.get("content") is None and not message.get("tool_calls"):
        # A model that returns nothing but reasoning tokens has answered without answering.
        return ProbeResult(
            EndpointState.COMPLETION_FAILED, "completion contained no content", model
        )
    return ProbeResult(EndpointState.OK, "completion returned", model)
