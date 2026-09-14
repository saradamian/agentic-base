"""A run exported to MLflow comes back with its authority intact, through MLflow's own client."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import mlflow
import pytest
from sqlmodel import Session

from agentic_base.db import get_engine, init_db
from agentic_base.domain.outcomes import LabelSource, RunRecordCreate
from agentic_base.domain.run_record import RunRecord
from agentic_base.provenance.mlflow_export import (
    RUN_ID_TAG,
    TRANSCRIPT_FIELDS,
    export_runs,
    main,
    outcome_metadata,
    span_attributes,
    to_mlflow,
)

CREATED = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def tracking(tmp_path_factory):
    """One backend for the module. MLflow's trace exporter is created once per process against
    the tracking URI in force at that moment; switching URIs per test sends later traces to a
    database the reader is no longer looking at. Async trace logging is left at MLflow's
    default on purpose: the exporter has to be correct under it, not only under the sync flag."""
    import os

    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    mlflow.set_tracking_uri(
        f"sqlite:///{tmp_path_factory.mktemp('mlflow') / 'mlflow.db'}"
    )
    yield


def _id() -> str:
    return uuid.uuid4().hex


def _run(**overrides) -> RunRecordCreate:
    base = dict(
        tenant="hpml",
        code_revision="ba38f821",
        component_versions={"surf-agentic-base": "0.3.1"},
        item="task-1",
        arm="full",
        model="glm-5.2",
        system_prompt="You are careful.",
        messages=[{"role": "user", "content": "fix it"}],
        resolved=True,
        label_source=LabelSource.OFFICIAL_HARNESS,
        instrument="swebench-official-harness",
        prompt_tokens=1200,
        completion_tokens=300,
    )
    base.update(overrides)
    return RunRecordCreate(**base)


def test_the_export_round_trips_the_outcome_with_its_authority(tracking) -> None:
    trace_id = to_mlflow(_run(), _id(), CREATED, experiment="probe")

    trace = mlflow.get_trace(trace_id)
    (assessment,) = [a for a in trace.info.assessments if a.name == "resolved"]
    assert assessment.feedback.value is True
    assert assessment.source.source_type == "CODE"
    assert assessment.source.source_id == "swebench-official-harness"
    assert assessment.metadata["agentic_base.authority"] == "authoritative"
    assert assessment.metadata["agentic_base.label_source"] == "official_harness"
    assert assessment.metadata["agentic_base.degraded"] == "false"


def test_the_span_carries_the_transcript_and_the_standard_attributes(tracking) -> None:
    trace_id = to_mlflow(_run(), _id(), CREATED, experiment="probe")

    (span,) = mlflow.get_trace(trace_id).data.spans
    assert span.inputs["system_prompt"] == "You are careful."
    assert span.attributes["openinference.span.kind"] == "AGENT"
    assert span.attributes["agentic_base.arm"] == "full"
    assert span.attributes["agentic_base.component_versions"] == {
        "surf-agentic-base": "0.3.1"
    }


def test_a_diagnostic_verdict_is_exported_as_diagnostic_not_hidden(tracking) -> None:
    trace_id = to_mlflow(
        _run(
            label_source=LabelSource.CONVENIENCE_VERIFIER,
            instrument="in-tree",
            degraded=True,
        ),
        _id(),
        CREATED,
        experiment="probe",
    )

    (assessment,) = mlflow.get_trace(trace_id).info.assessments
    assert assessment.source.source_type == "CODE"  # same modality as the harness...
    assert (
        assessment.metadata["agentic_base.authority"] == "diagnostic"
    )  # ...different standing
    assert assessment.metadata["agentic_base.degraded"] == "true"


def test_an_unlabelled_run_exports_no_assessment(tracking) -> None:
    trace_id = to_mlflow(
        _run(resolved=None, label_source=LabelSource.UNLABELLED, instrument=""),
        _id(),
        CREATED,
        experiment="probe",
    )

    assert mlflow.get_trace(trace_id).info.assessments == []


def test_the_metadata_names_every_fact_the_source_type_cannot() -> None:
    keys = set(outcome_metadata(_run(), "agentic-base"))

    assert keys == {
        "agentic_base.label_source",
        "agentic_base.authority",
        "agentic_base.degraded",
        "agentic_base.instrument",
        "agentic_base.writer",
    }


def test_every_field_of_the_record_is_exported_somewhere() -> None:
    """A field added to the record is exported without anyone editing this module."""
    attributes = span_attributes(_run(), "abc", CREATED)
    exported = {k.removeprefix("agentic_base.") for k in attributes} | set(
        TRANSCRIPT_FIELDS
    )

    assert set(RunRecordCreate.model_fields) <= exported


def test_the_transparency_and_oversight_fields_reach_mlflow(tracking) -> None:
    run = _run(disclosure="banner on every reply", content_marking="c2pa:urn:x")
    trace_id = to_mlflow(run, _id(), CREATED, experiment="probe")

    (span,) = mlflow.get_trace(trace_id).data.spans
    assert span.attributes["agentic_base.disclosure"] == "banner on every reply"
    assert span.attributes["agentic_base.content_marking"] == "c2pa:urn:x"


def test_exporting_leaves_the_callers_active_experiment_alone(tracking) -> None:
    mine = mlflow.set_experiment("the-callers-own")

    to_mlflow(_run(), _id(), CREATED, experiment="probe")

    assert mlflow.tracking.fluent._get_experiment_id() == mine.experiment_id


def test_exporting_the_same_run_twice_returns_the_trace_already_there(tracking) -> None:
    run_id = _id()
    first = to_mlflow(_run(), run_id, CREATED, experiment="probe")
    second = to_mlflow(_run(), run_id, CREATED, experiment="probe")

    experiment = mlflow.get_experiment_by_name("probe")
    assert experiment is not None
    found = mlflow.search_traces(
        locations=[experiment.experiment_id],
        filter_string=f"tag.`{RUN_ID_TAG}` = '{run_id}'",
        return_type="list",
    )
    assert second == first
    assert len(found) == 1


def test_a_batch_export_says_how_many_it_wrote_and_how_many_were_there(
    tracking,
) -> None:
    runs = [(_run(item=f"t{n}"), _id(), CREATED) for n in range(3)]

    assert export_runs(runs[:2], experiment="batch") == (2, 0)
    assert export_runs(runs, experiment="batch") == (1, 2)


def test_the_command_exports_a_tenant_from_the_service_database(
    tracking, capsys
) -> None:
    init_db()
    tenant = f"cmd-{_id()}"
    with Session(get_engine()) as session:
        for item in ("a", "b"):
            session.add(
                RunRecord(tenant=tenant, item=item, arm="x", code_revision="abc")
            )
        session.commit()

    main(["--tenant", tenant, "--experiment", "from-the-command"])
    main(["--tenant", tenant, "--experiment", "from-the-command"])

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"tenant {tenant}: 2 run(s); exported 2, already in experiment 'from-the-command' 0",
        f"tenant {tenant}: 2 run(s); exported 0, already in experiment 'from-the-command' 2",
    ]
