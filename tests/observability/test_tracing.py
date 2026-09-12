"""The service opens spans, and the SDK's own variables govern it."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentic_base.observability.tracing import configure_tracing, exporter_from_env


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/runs/{run_id}")
    def read(run_id: str) -> dict[str, str]:
        return {"run_id": run_id}

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_a_request_produces_a_server_span_carrying_the_route(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    exporter = InMemorySpanExporter()
    app = _app()
    assert configure_tracing(app, exporter=exporter) is not None

    TestClient(app).get("/runs/abc")

    spans = exporter.get_finished_spans()
    server = [
        s
        for s in spans
        if s.attributes and s.attributes.get("http.route") == "/runs/{run_id}"
    ]
    assert server, [s.name for s in spans]
    assert server[0].resource.attributes["service.name"] == "agentic-base"


def test_the_service_name_comes_from_the_standard_variable(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    monkeypatch.setenv("OTEL_SERVICE_NAME", "runs-referee")
    exporter = InMemorySpanExporter()
    app = _app()
    configure_tracing(app, exporter=exporter)

    TestClient(app).get("/runs/abc")

    assert (
        exporter.get_finished_spans()[0].resource.attributes["service.name"]
        == "runs-referee"
    )


def test_excluded_urls_open_no_span(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    exporter = InMemorySpanExporter()
    app = _app()
    configure_tracing(app, exporter=exporter, excluded_urls="/health/.*")

    TestClient(app).get("/health/live")

    assert exporter.get_finished_spans() == ()


def test_the_standard_off_switch_is_honoured(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    exporter = InMemorySpanExporter()
    app = _app()

    assert configure_tracing(app, exporter=exporter) is None
    TestClient(app).get("/runs/abc")
    assert exporter.get_finished_spans() == ()


@pytest.mark.parametrize(
    ("exporter", "endpoint", "expected"),
    [
        ("", "", None),
        ("none", "http://collector:4318", None),
        ("console", "", "ConsoleSpanExporter"),
        ("", "http://collector:4318", "OTLPSpanExporter"),
        ("otlp", "", "OTLPSpanExporter"),
    ],
)
def test_the_exporter_follows_the_sdk_variables(
    monkeypatch, exporter, endpoint, expected
) -> None:
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", exporter)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
    if not exporter:
        monkeypatch.delenv("OTEL_TRACES_EXPORTER")
    if not endpoint:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    chosen = exporter_from_env()

    assert (None if chosen is None else type(chosen).__name__) == expected


def test_an_unknown_exporter_is_refused_rather_than_silently_none(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "jaeger")

    with pytest.raises(ValueError, match="jaeger"):
        exporter_from_env()
