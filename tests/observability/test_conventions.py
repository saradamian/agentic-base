"""The span vocabulary.

The point of these is that the names on the wire belong to the standard. A span exported under a
private name is one no backend can label, and that is not a cosmetic problem: it is the difference
between telemetry a tool can read and telemetry only we can read.
"""

from __future__ import annotations

import agentic_base.observability.conventions as c


def test_every_span_carries_a_standard_kind() -> None:
    assert c.standard_attributes("llm", {})[c.OI_SPAN_KIND] == c.KIND_LLM


def test_an_unknown_kind_becomes_a_chain_rather_than_being_dropped() -> None:
    """Chain is the standard's own word for an untyped sub-operation, so nothing is unlabelled."""
    assert c.span_kind("something-new") == c.KIND_CHAIN
    assert c.span_kind("") == c.KIND_CHAIN


def test_an_attribute_is_emitted_under_both_standards_when_both_have_a_name() -> None:
    """The two vocabularies cover different ground, so an attribute both name gets both."""
    out = c.standard_attributes("llm", {"model": "some-model"})

    assert out[c.OI_LLM_MODEL_NAME] == "some-model"
    assert out[c.GEN_AI_REQUEST_MODEL] == "some-model"


def test_the_private_name_is_dropped_once_a_standard_one_exists() -> None:
    """A new consumer reads the standard name, and carrying both doubles every span."""
    out = c.standard_attributes("llm", {"model": "m"})

    assert "model" not in out


def test_migrating_consumers_can_ask_for_the_private_name_as_well() -> None:
    out = c.standard_attributes("llm", {"model": "m"}, keep_original_names=True)

    assert out["model"] == "m"
    assert out[c.OI_LLM_MODEL_NAME] == "m"


def test_an_attribute_with_no_standard_name_passes_through_unchanged() -> None:
    """Nothing is discarded for lacking a standard equivalent."""
    out = c.standard_attributes("tool", {"tenant": "hpml"})

    assert out["tenant"] == "hpml"


def test_token_counts_reach_both_vocabularies() -> None:
    out = c.standard_attributes("llm", {"prompt_tokens": 10, "completion_tokens": 2})

    assert out[c.OI_LLM_TOKEN_COUNT_PROMPT] == 10
    assert out[c.GEN_AI_USAGE_OUTPUT_TOKENS] == 2


def test_a_missing_value_is_omitted_rather_than_recorded_as_empty() -> None:
    """An absent attribute and an attribute that is empty are different facts."""
    assert "model" not in c.standard_attributes("llm", {"model": None})


def test_a_structured_value_is_serialised_rather_than_dropped() -> None:
    """A span attribute must be a primitive, and losing the value silently is the worse option."""
    out = c.standard_attributes("tool", {"args": {"path": "/tmp/x"}})

    assert "/tmp/x" in out["args"]


def test_a_homogeneous_list_survives_as_a_list() -> None:
    assert c.coerce_attribute(["a", "b"]) == ["a", "b"]


def test_a_value_that_cannot_be_serialised_still_records_something() -> None:
    class _Awkward:
        def __repr__(self) -> str:
            return "awkward"

    assert "awkward" in str(c.coerce_attribute(_Awkward()))


def test_the_attribute_names_are_the_standards_even_without_the_packages() -> None:
    """Both libraries are optional. The names on the wire must not depend on that.

    This is the check that matters for a deployment with a minimal install: it would otherwise
    export private names and nobody would notice until a backend showed unlabelled spans.
    """
    assert c.OI_SPAN_KIND == "openinference.span.kind"
    assert c.GEN_AI_REQUEST_MODEL == "gen_ai.request.model"
    assert c.OI_LLM_TOKEN_COUNT_PROMPT == "llm.token_count.prompt"


def test_both_vocabularies_are_installed_so_the_fallback_is_not_what_runs() -> None:
    """The literal fallbacks exist for an install without the packages. The suite is not one."""
    import openinference.semconv.trace  # noqa: F401
    from opentelemetry.semconv._incubating.attributes import (
        gen_ai_attributes,  # noqa: F401
    )


def test_every_fallback_literal_equals_the_installed_vocabulary() -> None:
    """A fallback that drifts from the package is a private dialect that appears only on the
    installs least likely to notice. Read the except branches and hold them to the live values."""
    import ast
    from pathlib import Path

    from agentic_base.observability import conventions

    source = Path(conventions.__file__).read_text()
    checked = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for stmt in handler.body:
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target, value = stmt.targets[0], stmt.value
                if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
                    assert getattr(conventions, target.id) == value.value, target.id
                    checked += 1
                elif isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple):
                    for name, const in zip(target.elts, value.elts, strict=True):
                        assert isinstance(name, ast.Name) and isinstance(
                            const, ast.Constant
                        )
                        assert getattr(conventions, name.id) == const.value, name.id
                        checked += 1
    assert checked >= 20, (
        f"only {checked} fallback literals found; the parser missed a branch"
    )
