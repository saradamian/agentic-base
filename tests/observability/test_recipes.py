"""The recipes in docs/OBSERVABILITY.md configure the exporter they say they configure."""

from __future__ import annotations

import base64

from agentic_base.observability.tracing import exporter_from_env


def _otlp(monkeypatch, **env: str):
    for key in (
        "OTEL_TRACES_EXPORTER",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    exporter = exporter_from_env()
    assert exporter is not None and type(exporter).__name__ == "OTLPSpanExporter"
    return exporter


def test_the_collector_recipe_posts_traces_to_the_collector(monkeypatch) -> None:
    exporter = _otlp(
        monkeypatch, OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4318"
    )

    assert exporter._endpoint == "http://otel-collector:4318/v1/traces"  # noqa: SLF001


def test_the_langfuse_recipe_posts_to_langfuse_with_basic_auth(monkeypatch) -> None:
    creds = base64.b64encode(b"pk-lf-1:sk-lf-2").decode()
    exporter = _otlp(
        monkeypatch,
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://cloud.langfuse.com/api/public/otel/v1/traces",
        OTEL_EXPORTER_OTLP_HEADERS=f"Authorization=Basic {creds}",
    )

    assert exporter._endpoint == "https://cloud.langfuse.com/api/public/otel/v1/traces"  # noqa: SLF001
    assert (
        exporter._headers["authorization"] == f"Basic {creds}"
    )  # the SDK lowercases keys  # noqa: SLF001


def test_the_phoenix_recipe_posts_to_phoenix_with_its_api_key(monkeypatch) -> None:
    exporter = _otlp(
        monkeypatch,
        OTEL_EXPORTER_OTLP_ENDPOINT="http://phoenix:6006",
        OTEL_EXPORTER_OTLP_HEADERS="api_key=abc",
    )

    assert exporter._endpoint == "http://phoenix:6006/v1/traces"  # noqa: SLF001
    assert exporter._headers["api_key"] == "abc"  # noqa: SLF001


def test_every_recipe_in_the_document_is_one_the_tests_cover() -> None:
    from pathlib import Path

    doc = (
        Path(__file__).resolve().parents[2] / "docs" / "OBSERVABILITY.md"
    ).read_text()
    recipes = [line[4:].strip() for line in doc.splitlines() if line.startswith("### ")]

    assert recipes == [
        "An OpenTelemetry Collector, Jaeger, or Grafana Tempo",
        "Langfuse",
        "Arize Phoenix",
    ], recipes


def test_a_traces_specific_endpoint_alone_selects_the_otlp_exporter(
    monkeypatch,
) -> None:
    """Langfuse's recipe sets only the traces endpoint; that must be enough to turn tracing on."""
    exporter = _otlp(
        monkeypatch, OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://x/v1/traces"
    )

    assert exporter._endpoint == "https://x/v1/traces"  # noqa: SLF001
