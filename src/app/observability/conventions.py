"""Span vocabulary, which is the standard's and not ours.

A span exported under a private name is a span no backend can label. Phoenix, Langfuse, LangSmith
and Jaeger all read the same two vocabularies, so this module is a lookup table from an
application's own words into theirs, and nothing else.

Two vocabularies rather than one, because they cover different ground today.

OpenInference carries span kinds, typed input and output messages, and tool-call substructure. It
has the longest track record for agent spans.

The OpenTelemetry GenAI conventions carry the `gen_ai.*` attributes. They were moved out of the
main semantic-conventions repository in June 2026 into a dedicated one with no versioned release
and no schema URL to pin, and the agent and tool-orchestration parts are still in development. So
they are set alongside OpenInference rather than instead of it, and whatever is built against them
should pin a version and expect churn.

Both packages are optional. When neither is installed every constant falls back to its literal
string, so the attribute names on the wire are still the standard's.
"""

from __future__ import annotations

import json
from typing import Any

# --- OpenInference ---------------------------------------------------------------------------
try:  # pragma: no cover - the installed-package path
    from openinference.semconv.trace import (
        MessageAttributes as _M,
        OpenInferenceSpanKindValues as _K,
        SpanAttributes as _S,
        ToolCallAttributes as _T,
    )

    OI_SPAN_KIND = _S.OPENINFERENCE_SPAN_KIND
    OI_LLM_MODEL_NAME = _S.LLM_MODEL_NAME
    OI_LLM_INPUT_MESSAGES = _S.LLM_INPUT_MESSAGES
    OI_LLM_OUTPUT_MESSAGES = _S.LLM_OUTPUT_MESSAGES
    OI_LLM_TOKEN_COUNT_PROMPT = _S.LLM_TOKEN_COUNT_PROMPT
    OI_LLM_TOKEN_COUNT_COMPLETION = _S.LLM_TOKEN_COUNT_COMPLETION
    OI_TOOL_NAME = _S.TOOL_NAME
    OI_TOOL_PARAMETERS = _S.TOOL_PARAMETERS
    OI_INPUT_VALUE = _S.INPUT_VALUE
    OI_OUTPUT_VALUE = _S.OUTPUT_VALUE
    OI_METADATA = _S.METADATA
    OI_SESSION_ID = _S.SESSION_ID
    OI_MESSAGE_ROLE = _M.MESSAGE_ROLE
    OI_MESSAGE_CONTENT = _M.MESSAGE_CONTENT
    OI_TOOL_CALL_FUNCTION_NAME = _T.TOOL_CALL_FUNCTION_NAME
    KIND_LLM, KIND_TOOL, KIND_AGENT, KIND_CHAIN, KIND_RETRIEVER, KIND_EVALUATOR = (
        _K.LLM.value,
        _K.TOOL.value,
        _K.AGENT.value,
        _K.CHAIN.value,
        _K.RETRIEVER.value,
        _K.EVALUATOR.value,
    )
except Exception:  # pragma: no cover - names stay standard without the package
    OI_SPAN_KIND = "openinference.span.kind"
    OI_LLM_MODEL_NAME = "llm.model_name"
    OI_LLM_INPUT_MESSAGES = "llm.input_messages"
    OI_LLM_OUTPUT_MESSAGES = "llm.output_messages"
    OI_LLM_TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
    OI_LLM_TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
    OI_TOOL_NAME = "tool.name"
    OI_TOOL_PARAMETERS = "tool.parameters"
    OI_INPUT_VALUE = "input.value"
    OI_OUTPUT_VALUE = "output.value"
    OI_METADATA = "metadata"
    OI_SESSION_ID = "session.id"
    OI_MESSAGE_ROLE = "message.role"
    OI_MESSAGE_CONTENT = "message.content"
    OI_TOOL_CALL_FUNCTION_NAME = "tool_call.function.name"
    KIND_LLM, KIND_TOOL, KIND_AGENT, KIND_CHAIN, KIND_RETRIEVER, KIND_EVALUATOR = (
        "LLM",
        "TOOL",
        "AGENT",
        "CHAIN",
        "RETRIEVER",
        "EVALUATOR",
    )

# --- OpenTelemetry GenAI, incubating ----------------------------------------------------------
try:  # pragma: no cover
    from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as _G

    GEN_AI_REQUEST_MODEL = _G.GEN_AI_REQUEST_MODEL
    GEN_AI_AGENT_NAME = _G.GEN_AI_AGENT_NAME
    GEN_AI_AGENT_VERSION = _G.GEN_AI_AGENT_VERSION
    GEN_AI_TOOL_NAME = _G.GEN_AI_TOOL_NAME
    GEN_AI_TOOL_DEFINITIONS = _G.GEN_AI_TOOL_DEFINITIONS
    GEN_AI_SYSTEM_INSTRUCTIONS = _G.GEN_AI_SYSTEM_INSTRUCTIONS
    GEN_AI_USAGE_INPUT_TOKENS = _G.GEN_AI_USAGE_INPUT_TOKENS
    GEN_AI_USAGE_OUTPUT_TOKENS = _G.GEN_AI_USAGE_OUTPUT_TOKENS
except Exception:  # pragma: no cover
    GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
    GEN_AI_AGENT_NAME = "gen_ai.agent.name"
    GEN_AI_AGENT_VERSION = "gen_ai.agent.version"
    GEN_AI_TOOL_NAME = "gen_ai.tool.name"
    GEN_AI_TOOL_DEFINITIONS = "gen_ai.tool.definitions"
    GEN_AI_SYSTEM_INSTRUCTIONS = "gen_ai.system_instructions"
    GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"


SPAN_KINDS: dict[str, str] = {
    "llm": KIND_LLM,
    "tool": KIND_TOOL,
    "agent": KIND_AGENT,
    "retrieval": KIND_RETRIEVER,
    "verification": KIND_EVALUATOR,
    "": KIND_CHAIN,
}
"""Application span kinds to the standard's. Anything unmapped is a chain, which is the
standard's own word for an untyped sub-operation."""


ATTRIBUTE_NAMES: dict[str, tuple[str, ...]] = {
    "model": (OI_LLM_MODEL_NAME, GEN_AI_REQUEST_MODEL),
    "tool_name": (OI_TOOL_NAME, GEN_AI_TOOL_NAME),
    "prompt_tokens": (OI_LLM_TOKEN_COUNT_PROMPT, GEN_AI_USAGE_INPUT_TOKENS),
    "completion_tokens": (OI_LLM_TOKEN_COUNT_COMPLETION, GEN_AI_USAGE_OUTPUT_TOKENS),
    "session_id": (OI_SESSION_ID,),
    "input": (OI_INPUT_VALUE,),
    "output": (OI_OUTPUT_VALUE,),
}
"""Application attribute names to their standard equivalents. An attribute with no standard name
passes through unchanged, so nothing is dropped for lacking one."""


def span_kind(kind: str) -> str:
    """The standard span kind for an application's own kind string."""
    return SPAN_KINDS.get(kind or "", KIND_CHAIN)


def standard_attributes(
    kind: str, attributes: dict[str, Any], *, keep_original_names: bool = False
) -> dict[str, Any]:
    """Attributes for a span, under the standard's names.

    `keep_original_names` emits the application's own key alongside the standard one. It defaults
    off, because a new consumer should read the standard name and carrying both doubles the
    attribute count on every span. Set it while migrating an existing consumer that reads the old
    names, then turn it off.

    Values are coerced, because a span attribute must be a primitive or a sequence of one kind.
    Anything else is serialised rather than dropped, and only a value that is genuinely absent
    disappears.
    """
    out: dict[str, Any] = {OI_SPAN_KIND: span_kind(kind)}
    for key, value in attributes.items():
        coerced = coerce_attribute(value)
        if coerced is None:
            continue
        standard = ATTRIBUTE_NAMES.get(key, ())
        for name in standard:
            out[name] = coerced
        if keep_original_names or not standard:
            out[key] = coerced
    return out


def coerce_attribute(value: Any) -> Any:
    """A span-safe form of a value, or None when there is nothing to record."""
    if value is None:
        return None
    if isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list | tuple) and all(
        isinstance(x, str | bool | int | float) for x in value
    ):
        return list(value)
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)
