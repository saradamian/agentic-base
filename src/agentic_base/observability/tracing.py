"""Tracing for the service half, configured the way the OpenTelemetry SDK expects.

The vocabulary in :mod:`.conventions` is worth nothing if the service never opens a span. This
wires the SDK's FastAPI instrumentation and an exporter chosen by the SDK's own environment
variables, so an operator configures it the way they configure every other OpenTelemetry
service and nothing here is a private knob:

* ``OTEL_SDK_DISABLED=true`` turns it off.
* ``OTEL_SERVICE_NAME`` and ``OTEL_RESOURCE_ATTRIBUTES`` name the service; the default name is
  the distribution's.
* ``OTEL_TRACES_EXPORTER`` selects ``otlp`` (the default when either endpoint variable is set),
  ``console`` or ``none``; ``OTEL_EXPORTER_OTLP_ENDPOINT``, ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``
  and their siblings configure the OTLP exporter.

With no exporter selected and no endpoint set, spans are recorded and dropped rather than sent
to a default address that is not listening. That case is instrumented and silent, and it is the
only situation in which a configured-looking service exports nothing; ``configure_tracing``
returns the provider so a caller can see which it got.
"""

from __future__ import annotations

import contextlib
import os
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

DISTRIBUTION = "surf-agentic-base"


def _disabled() -> bool:
    return os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() in {"true", "1"}


def _resource() -> Resource:
    attributes: dict[str, str] = {}
    if "OTEL_SERVICE_NAME" not in os.environ:
        attributes[SERVICE_NAME] = DISTRIBUTION
    with contextlib.suppress(PackageNotFoundError):
        attributes[SERVICE_VERSION] = version(DISTRIBUTION)
    return Resource.create(attributes)


def exporter_from_env() -> SpanExporter | None:
    """The exporter the SDK's variables select, or None for none."""
    choice = os.environ.get("OTEL_TRACES_EXPORTER", "").strip().lower()
    if not choice:
        endpoint_set = any(
            os.environ.get(k)
            for k in (
                "OTEL_EXPORTER_OTLP_ENDPOINT",
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            )
        )
        choice = "otlp" if endpoint_set else "none"
    if choice == "none":
        return None
    if choice == "console":
        return ConsoleSpanExporter()
    if choice == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter()
    raise ValueError(
        f"OTEL_TRACES_EXPORTER={choice!r} is not one of otlp, console, none"
    )


def configure_tracing(
    app: FastAPI,
    *,
    exporter: SpanExporter | None = None,
    excluded_urls: str = "",
) -> TracerProvider | None:
    """Instrument *app*. Returns the provider, or None when the SDK is disabled.

    An explicit *exporter* is attached synchronously, which is what a test wants; one chosen
    from the environment is batched, which is what production wants.
    """
    if _disabled():
        return None
    provider = TracerProvider(resource=_resource())
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        chosen = exporter_from_env()
        if chosen is not None:
            provider.add_span_processor(BatchSpanProcessor(chosen))
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls=excluded_urls or None
    )
    # Libraries that trace themselves, the MCP SDK among them, ask the API for the global
    # provider at import time and get a proxy that forwards to whatever is set later. Nothing
    # they emit leaves the process unless this is set. It can be set once; a second call sees
    # the first provider and attaches its exporter there instead of losing it.
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        for processor in provider._active_span_processor._span_processors:  # noqa: SLF001
            current.add_span_processor(processor)
        provider = current
    else:
        trace.set_tracer_provider(provider)
    app.state.tracer_provider = provider
    return provider
