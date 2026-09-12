"""Export a run into MLflow as a trace with assessments.

MLflow is adopted as the trace UI and the export target, not as the store: measured on
2026-09-12, its API accepts an outcome with no scorer and stamps it ``CODE/default``, so the
refusal this platform exists for has to live at our boundary. Once a record has passed that
boundary it can be handed to MLflow whole, and this is the hand-off.

The run becomes one trace carrying one span with the standard attributes and the transcript as
inputs and outputs. The outcome becomes a feedback assessment whose source type is the MLflow
modality our label source maps onto, and whose metadata carries the two facts MLflow has no
field for, the label source and its authority, plus the degraded flag and the writer. A reader
of the MLflow UI sees a CODE verdict; a reader of the metadata can tell whether it may be cited.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agentic_base.domain.outcomes import (
    RunRecordCreate,
    authority_of,
    mlflow_source_type,
)
from agentic_base.observability.conventions import span_kind, standard_attributes

EXTRA = "mlflow"
METADATA_PREFIX = "agentic_base"


def _need() -> None:
    raise ImportError(
        f"mlflow is not installed; export needs the {EXTRA!r} extra: "
        f"pip install 'surf-agentic-base[{EXTRA}]'"
    )


def outcome_metadata(run: RunRecordCreate, writer: str) -> dict[str, str]:
    """What rides in the assessment's metadata: the axis MLflow's source type lacks."""
    return {
        f"{METADATA_PREFIX}.label_source": run.label_source.value,
        f"{METADATA_PREFIX}.authority": authority_of(run.label_source).value,
        f"{METADATA_PREFIX}.degraded": str(run.degraded).lower(),
        f"{METADATA_PREFIX}.instrument": run.instrument,
        f"{METADATA_PREFIX}.writer": writer,
    }


def to_mlflow(
    run: RunRecordCreate,
    run_id: str,
    created_at: datetime,
    *,
    experiment: str = "agentic-base",
    writer: str = "agentic-base",
) -> str:
    """Write *run* into the active MLflow tracking backend. Returns the MLflow trace id.

    The caller configures the backend the MLflow way, ``MLFLOW_TRACKING_URI`` or
    ``mlflow.set_tracking_uri``; nothing here is a private knob.
    """
    try:
        import mlflow
        from mlflow.entities import AssessmentSource
    except ImportError:
        _need()

    mlflow.set_experiment(experiment)
    attributes: dict[str, Any] = dict(
        standard_attributes(
            "agent",
            {
                "model": run.model,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
            },
        )
    )
    attributes.update(
        {
            "openinference.span.kind": span_kind("agent"),
            f"{METADATA_PREFIX}.run_id": run_id,
            f"{METADATA_PREFIX}.tenant": run.tenant,
            f"{METADATA_PREFIX}.item": run.item,
            f"{METADATA_PREFIX}.arm": run.arm,
            f"{METADATA_PREFIX}.arm_fingerprint": run.arm_fingerprint,
            f"{METADATA_PREFIX}.code_revision": run.code_revision,
            f"{METADATA_PREFIX}.component_versions": dict(run.component_versions),
            f"{METADATA_PREFIX}.status": run.status.value,
            f"{METADATA_PREFIX}.failure_kind": run.failure_kind,
            f"{METADATA_PREFIX}.created_at": created_at.isoformat(),
            f"{METADATA_PREFIX}.endpoint": run.endpoint,
            f"{METADATA_PREFIX}.precision": run.precision,
            f"{METADATA_PREFIX}.joules": run.joules,
            f"{METADATA_PREFIX}.elapsed_ms": run.elapsed_ms,
        }
    )
    with mlflow.start_span(name=f"run {run_id}", attributes=attributes) as span:
        span.set_inputs({"system_prompt": run.system_prompt, "messages": run.messages})
        span.set_outputs({"status": run.status.value, "resolved": run.resolved})
    trace_id: str = span.trace_id
    if not trace_id or "NO_OP" in trace_id:
        # MLflow hands back a no-op span when tracing could not start, and a caller that did not
        # check would file the run under a sentinel. Refuse, rather than report an export that
        # stored nothing.
        raise RuntimeError(
            "MLflow returned a no-op span; tracing did not start (check the tracking URI and "
            "whether a warning was raised inside mlflow.start_span)"
        )
    # The trace must exist before an assessment can attach to it. With async trace logging on,
    # MLflow's default, the span is still in a queue here and log_feedback fails with "trace not
    # found"; flushing makes the export correct under either setting rather than only the one the
    # tests happen to choose.
    mlflow.flush_trace_async_logging()

    if run.resolved is not None:
        mlflow.log_feedback(
            trace_id=trace_id,
            name="resolved",
            value=run.resolved,
            source=AssessmentSource(
                source_type=mlflow_source_type(run.label_source),
                source_id=run.instrument or run.label_source.value,
            ),
            metadata=outcome_metadata(run, writer),
        )
    return trace_id
