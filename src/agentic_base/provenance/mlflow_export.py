"""Export runs into MLflow as traces with assessments.

MLflow is adopted as the trace UI and the export target, not as the store: measured on
2026-09-12, its API accepts an outcome with no scorer and stamps it ``CODE/default``, so the
refusal this platform exists for has to live at our boundary. Once a record has passed that
boundary it can be handed to MLflow whole, and this is the hand-off.

A run becomes one trace with one span. The transcript is the span's inputs; every other field of
the record is a span attribute under ``agentic_base.``, taken from the record's own field list so
a field added to the record is exported without anyone remembering to. The outcome is also a
feedback assessment whose source type is the MLflow modality our label source maps onto, and
whose metadata carries the facts MLflow has no field for: the label source, its authority, the
degraded flag and the writer.

The export goes through ``MlflowClient`` with an explicit experiment, so it never changes the
caller's active experiment, and it tags each trace with the run id, so exporting the same run
twice returns the trace already there instead of a duplicate.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentic_base.domain.outcomes import (
    RunRecordCreate,
    authority_of,
    mlflow_source_type,
)
from agentic_base.observability.conventions import span_kind, standard_attributes

if TYPE_CHECKING:
    from mlflow import MlflowClient

EXTRA = "mlflow"
METADATA_PREFIX = "agentic_base"
RUN_ID_TAG = f"{METADATA_PREFIX}.run_id"
TRANSCRIPT_FIELDS = ("system_prompt", "messages")
"""Fields that travel as the span's inputs rather than as attributes."""


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


def span_attributes(
    run: RunRecordCreate, run_id: str, created_at: datetime
) -> dict[str, Any]:
    """The standard attributes, then every non-transcript field of the record."""
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
    attributes["openinference.span.kind"] = span_kind("agent")
    values = run.model_dump(mode="json", exclude=set(TRANSCRIPT_FIELDS))
    attributes.update({f"{METADATA_PREFIX}.{k}": v for k, v in values.items()})
    attributes[RUN_ID_TAG] = run_id
    attributes[f"{METADATA_PREFIX}.created_at"] = created_at.isoformat()
    return attributes


def _experiment_id(client: MlflowClient, name: str) -> str:
    found = client.get_experiment_by_name(name)
    if found is not None:
        return str(found.experiment_id)
    try:
        return str(client.create_experiment(name))
    except Exception:  # another writer created it between the two calls
        again = client.get_experiment_by_name(name)
        if again is None:
            raise
        return str(again.experiment_id)


def _existing_trace(
    client: MlflowClient, experiment_id: str, run_id: str
) -> str | None:
    quoted = run_id.replace("'", "\\'")
    found = client.search_traces(
        locations=[experiment_id],
        filter_string=f"tag.`{RUN_ID_TAG}` = '{quoted}'",
        max_results=1,
        include_spans=False,
    )
    return str(found[0].info.trace_id) if found else None


def _export(
    run: RunRecordCreate,
    run_id: str,
    created_at: datetime,
    *,
    experiment: str,
    writer: str,
) -> tuple[str, bool]:
    """The trace id, and whether this call wrote it (False when the run was already there)."""
    try:
        import mlflow
        from mlflow import MlflowClient
        from mlflow.entities import AssessmentSource
    except ImportError:
        _need()

    client = MlflowClient()
    experiment_id = _experiment_id(client, experiment)
    existing = _existing_trace(client, experiment_id, run_id)
    if existing is not None:
        return existing, False

    span = client.start_trace(
        name=f"run {run_id}",
        span_type="AGENT",
        inputs={"system_prompt": run.system_prompt, "messages": run.messages},
        attributes=span_attributes(run, run_id, created_at),
        tags={RUN_ID_TAG: run_id},
        experiment_id=experiment_id,
    )
    trace_id: str = span.trace_id
    if not trace_id or "NO_OP" in trace_id:
        # MLflow hands back a no-op span when tracing could not start, and a caller that did not
        # check would file the run under a sentinel. Refuse, rather than report an export that
        # stored nothing.
        raise RuntimeError(
            "MLflow returned a no-op span; tracing did not start (check the tracking URI and "
            "whether a warning was raised inside start_trace)"
        )
    client.end_trace(
        trace_id, outputs={"status": run.status.value, "resolved": run.resolved}
    )
    # The trace must exist before an assessment can attach to it. With async trace logging on,
    # MLflow's default, it is still in a queue here and log_feedback fails with "trace not
    # found"; flushing makes the export correct under either setting.
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
    return trace_id, True


def to_mlflow(
    run: RunRecordCreate,
    run_id: str,
    created_at: datetime,
    *,
    experiment: str = "agentic-base",
    writer: str = "agentic-base",
) -> str:
    """Write *run* into the MLflow tracking backend. Returns the MLflow trace id.

    The caller configures the backend the MLflow way, ``MLFLOW_TRACKING_URI`` or
    ``mlflow.set_tracking_uri``; nothing here is a private knob. A run already exported to the
    experiment returns its existing trace.
    """
    return _export(run, run_id, created_at, experiment=experiment, writer=writer)[0]


def export_runs(
    runs: Iterable[tuple[RunRecordCreate, str, datetime]],
    *,
    experiment: str = "agentic-base",
    writer: str = "agentic-base",
) -> tuple[int, int]:
    """Export ``(run, run_id, created_at)`` triples. Returns (written now, already there)."""
    written = present = 0
    for run, run_id, created_at in runs:
        _, new = _export(run, run_id, created_at, experiment=experiment, writer=writer)
        written += new
        present += not new
    return written, present


def main(argv: list[str] | None = None) -> None:
    """Export a tenant's runs from the service's database into MLflow.

    Reads the service's settings for the database and ``MLFLOW_TRACKING_URI`` for the backend.
    Runs already in the experiment are left as they are, so it can be run again.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-base-mlflow", description=main.__doc__
    )
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--experiment", default="agentic-base")
    args = parser.parse_args(argv)

    from sqlmodel import Session, col, select

    from agentic_base.db import get_engine, init_db
    from agentic_base.domain.run_record import RunRecord, to_payload

    init_db()
    with Session(get_engine()) as session:
        records = session.exec(
            select(RunRecord)
            .where(RunRecord.tenant == args.tenant)
            .order_by(col(RunRecord.created_at))
        ).all()
        triples = [(to_payload(r), r.run_id, r.created_at) for r in records]
    written, present = export_runs(triples, experiment=args.experiment)
    print(
        f"tenant {args.tenant}: {len(triples)} run(s); exported {written}, "
        f"already in experiment {args.experiment!r} {present}"
    )


if __name__ == "__main__":
    main()
