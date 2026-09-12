# Observability: what the service emits, and where to point it

Three signals, three standard channels, nothing private. An operator configures this service
the way they configure every other OpenTelemetry service.

| signal | mechanism | configured by |
|---|---|---|
| logs | structlog, one JSON line per record, a correlation id per request | `LOG_JSON_FORMAT`, `LOG_LEVEL` |
| metrics | Prometheus, via the FastAPI instrumentator | `METRICS_PORT`, or scrape the app |
| traces | OpenTelemetry SDK: HTTP server spans, and every MCP call the SDK traces | the standard `OTEL_*` variables below |

The service opens no LLM or agent spans, because it makes no LLM calls: it is the record, not
the agent. The span vocabulary in `agentic_base.observability.conventions` is for a consumer
that runs an agent and wants its spans labelled the way Phoenix, Langfuse and LangSmith read
them.

## Traces: the variables

```bash
OTEL_SDK_DISABLED=true                       # off
OTEL_SERVICE_NAME=runs-referee               # default: surf-agentic-base
OTEL_TRACES_EXPORTER=otlp|console|none       # default: otlp when either endpoint variable is set, else none
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
OTEL_EXPORTER_OTLP_HEADERS=key=value,key2=value2
```

With no exporter and no endpoint, spans are recorded and dropped. That is the one silent
configuration, and `configure_tracing` returns the provider so a caller can see which it got.
An unknown exporter name is refused rather than treated as none.

## Recipes

Each block below is held by a test (`tests/observability/test_recipes.py`) that sets exactly
these variables and checks the exporter the SDK builds from them: the endpoint it will post to
and the headers it will send. That tests our side of the contract. It does not test the
backend, which is theirs.

### An OpenTelemetry Collector, Jaeger, or Grafana Tempo

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
```

The HTTP exporter appends `/v1/traces`.

### Langfuse

Langfuse ingests OTLP over HTTP at `/api/public/otel`, authenticated with a Basic header built
from a public and a secret key.

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic $(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)"
```

Use the traces-specific endpoint variable, because Langfuse's path already ends in `/otel` and
the generic one would have `/v1/traces` appended after it, which is what you want, but only
once. For a self-hosted Langfuse replace the host.

### Arize Phoenix

Phoenix ingests OTLP over HTTP on its own port.

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:6006
```

A hosted Phoenix wants an API key: `OTEL_EXPORTER_OTLP_HEADERS="api_key=$PHOENIX_API_KEY"`.

## Provenance is not telemetry

A run's provenance in W3C PROV, OpenLineage or a Process Run Crate comes from
`GET /runs/{run_id}/provenance?format=...`, and an export into MLflow from
`agentic_base.provenance.mlflow_export`. Those are records of what a run was; the signals above
are records of what this service did while serving them.
