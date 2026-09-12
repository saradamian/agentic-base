"""Each emitter's output is read back by that standard's own library, and the authority of the
outcome label survives the round trip in every format."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentic_base.domain.outcomes import LabelSource, RunRecordCreate, RunStatus
from agentic_base.provenance import (
    OUTCOME_FACET_SCHEMA,
    PROCESS_RUN_CRATE_PROFILE,
    to_openlineage,
    to_process_run_crate,
    to_prov,
)

CREATED = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def _run(**overrides) -> RunRecordCreate:
    base = dict(
        tenant="hpml",
        code_revision="ba38f821",
        component_versions={"surf-agentic-base": "0.2.0"},
        item="task-1",
        arm="full",
        arm_fingerprint="10d6b5b3fa11",
        model="glm-5.2",
        resolved=True,
        label_source=LabelSource.OFFICIAL_HARNESS,
        prompt_tokens=1200,
        completion_tokens=300,
        joules=41.5,
    )
    base.update(overrides)
    return RunRecordCreate(**base)


def test_prov_attributes_the_outcome_to_the_scorer_and_survives_a_round_trip() -> None:
    from prov.model import ProvDocument

    doc = to_prov(_run(), "abc", CREATED)
    text = doc.serialize(format="json")
    back = ProvDocument.deserialize(content=text, format="json")

    assert len(back.get_records()) == len(doc.get_records())
    payload = json.loads(text)
    (outcome,) = [v for k, v in payload["entity"].items() if k.endswith("/outcome")]
    assert outcome["ab:authority"] == "authoritative"
    assert outcome["ab:label_source"] == "official_harness"
    assert "wasAttributedTo" in payload


def test_prov_records_no_outcome_for_an_unlabelled_run() -> None:
    payload = json.loads(
        to_prov(
            _run(resolved=None, label_source=LabelSource.UNLABELLED), "abc", CREATED
        ).serialize(format="json")
    )

    assert not any(k.endswith("/outcome") for k in payload["entity"])
    assert "wasAttributedTo" not in payload


def test_openlineage_event_carries_authority_in_a_declared_facet() -> None:
    from openlineage.client.serde import Serde

    event = json.loads(
        Serde.to_json(
            to_openlineage(_run(), "c5a4b1e0-0000-4000-8000-000000000001", CREATED)
        )
    )

    facet = event["run"]["facets"]["agenticBaseOutcome"]
    assert facet["_schemaURL"] == OUTCOME_FACET_SCHEMA
    assert facet["authority"] == "authoritative"
    assert facet["joules"] == 41.5
    assert event["job"] == {"namespace": "hpml", "name": "full", "facets": {}}
    assert event["run"]["facets"]["processing_engine"]["version"] == "0.2.0"
    assert event["eventType"] == "COMPLETE"


def test_openlineage_marks_a_diagnostic_label_as_such() -> None:
    from openlineage.client.serde import Serde

    event = json.loads(
        Serde.to_json(
            to_openlineage(
                _run(label_source=LabelSource.CONVENIENCE_VERIFIER, degraded=True),
                "c5a4b1e0-0000-4000-8000-000000000002",
                CREATED,
            )
        )
    )

    facet = event["run"]["facets"]["agenticBaseOutcome"]
    assert facet["authority"] == "diagnostic"
    assert facet["degraded"] is True


def test_openlineage_event_type_follows_the_run_status() -> None:
    event = to_openlineage(
        _run(
            status=RunStatus.INFRASTRUCTURE_ERROR,
            failure_kind="container_removed",
            resolved=None,
            label_source=LabelSource.UNLABELLED,
        ),
        "c5a4b1e0-0000-4000-8000-000000000003",
        CREATED,
    )

    assert event.eventType is not None and event.eventType.value == "FAIL"


def test_the_facet_schema_file_names_every_property_the_facet_emits() -> None:
    from pathlib import Path

    from openlineage.client.serde import Serde

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "schemas"
            / "OutcomeRunFacet.json"
        ).read_text()
    )
    event = json.loads(
        Serde.to_json(
            to_openlineage(_run(), "c5a4b1e0-0000-4000-8000-000000000004", CREATED)
        )
    )
    emitted = {
        k for k in event["run"]["facets"]["agenticBaseOutcome"] if not k.startswith("_")
    }

    assert emitted == set(schema["properties"]), emitted ^ set(schema["properties"])
    assert schema["$id"] == OUTCOME_FACET_SCHEMA


def test_process_run_crate_reloads_and_conforms_to_the_profile(tmp_path) -> None:
    from rocrate.rocrate import ROCrate

    metadata = to_process_run_crate(_run(), "abc", CREATED, tmp_path)
    crate = ROCrate(tmp_path)

    assert metadata.exists()
    profile = crate.root_dataset["conformsTo"]
    assert (
        profile if isinstance(profile, str) else profile["@id"]
    ) == PROCESS_RUN_CRATE_PROFILE
    action = crate.dereference("#abc")
    assert action["@type"] == "CreateAction"
    results = {r["name"]: r["value"] for r in action["result"]}
    assert results["authority"] == "authoritative"
    assert results["label_source"] == "official_harness"
    objects = {o["name"]: o["value"] for o in action["object"]}
    assert objects["joules"] == "41.5"
    assert json.loads(objects["component_versions"]) == {"surf-agentic-base": "0.2.0"}


def test_a_failed_run_is_a_failed_action_with_no_result(tmp_path) -> None:
    from rocrate.rocrate import ROCrate

    to_process_run_crate(
        _run(
            status=RunStatus.TIMEOUT,
            failure_kind="timeout@7200",
            resolved=None,
            label_source=LabelSource.UNLABELLED,
        ),
        "abc",
        CREATED,
        tmp_path,
    )
    action = ROCrate(tmp_path).dereference("#abc")

    status = action["actionStatus"]
    assert (status if isinstance(status, str) else status["@id"]).endswith(
        "FailedActionStatus"
    )
    assert "result" not in action


def test_the_module_imports_without_the_extra_and_names_it_when_called(
    monkeypatch,
) -> None:
    import builtins
    import importlib

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith(("prov", "openlineage", "rocrate")):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    module = importlib.import_module("agentic_base.provenance.emit")
    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(ImportError, match=r"surf-agentic-base\[provenance\]"):
        module.to_prov(_run(), "abc", CREATED)


def test_a_run_id_that_is_not_a_uuid_becomes_a_stable_uuid_and_travels_in_the_facet() -> (
    None
):
    from openlineage.client.serde import Serde

    from agentic_base.provenance import openlineage_run_id

    first = json.loads(Serde.to_json(to_openlineage(_run(), "journal-42", CREATED)))
    second = json.loads(Serde.to_json(to_openlineage(_run(), "journal-42", CREATED)))

    assert (
        first["run"]["runId"]
        == second["run"]["runId"]
        == openlineage_run_id("journal-42")
    )
    assert first["run"]["runId"] != "journal-42"
    assert first["run"]["facets"]["agenticBaseOutcome"]["sourceRunId"] == "journal-42"


def test_a_run_id_that_is_a_uuid_is_kept_as_is() -> None:
    from agentic_base.provenance import openlineage_run_id

    assert (
        openlineage_run_id("C5A4B1E0-0000-4000-8000-000000000001")
        == "c5a4b1e0-0000-4000-8000-000000000001"
    )
