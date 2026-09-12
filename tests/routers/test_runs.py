"""End-to-end tests for the run endpoints."""

from agentic_base.domain.run_record import LabelSource, RunStatus


def _payload(**kwargs) -> dict:
    body = {
        "tenant": "hpml",
        "code_revision": "abc1234",
        "item": "task-1",
        "arm": "baseline",
    }
    body.update(kwargs)
    return body


def test_a_recorded_run_can_be_retrieved_by_its_id(test_client) -> None:
    created = test_client.post("/runs", json=_payload()).json()

    fetched = test_client.get(f"/runs/{created['run_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == created["run_id"]


def test_retrieving_an_unknown_run_reports_not_found(test_client) -> None:
    assert test_client.get("/runs/does-not-exist").status_code == 404


def test_labelling_a_run_records_who_decided_and_when(test_client) -> None:
    created = test_client.post("/runs", json=_payload(item="task-2")).json()

    labelled = test_client.post(
        f"/runs/{created['run_id']}/label",
        json={"resolved": True, "label_source": LabelSource.OFFICIAL_HARNESS.value},
    ).json()

    assert labelled["resolved"] is True
    assert labelled["label_source"] == LabelSource.OFFICIAL_HARNESS.value
    assert labelled["labelled_at"] is not None


def test_a_label_without_a_source_is_rejected(test_client) -> None:
    """Provenance is mandatory by construction, not by convention."""
    created = test_client.post("/runs", json=_payload(item="task-3")).json()

    response = test_client.post(
        f"/runs/{created['run_id']}/label", json={"resolved": True}
    )

    assert response.status_code == 422


def test_the_validity_report_flags_an_arm_correlated_exclusion(test_client) -> None:
    tenant = "skewed"
    for n in range(20):
        test_client.post(
            "/runs", json=_payload(tenant=tenant, item=f"t{n}", arm="shallow")
        )
    for n in range(20):
        excluded = n < 6
        test_client.post(
            "/runs",
            json=_payload(
                tenant=tenant,
                item=f"t{n}",
                arm="deep",
                status=RunStatus.INFRASTRUCTURE_ERROR.value
                if excluded
                else RunStatus.COMPLETED.value,
                failure_kind="container_removed" if excluded else "",
            ),
        )

    report = test_client.get("/runs/validity/report", params={"tenant": tenant}).json()

    assert report["could_have_flagged"] is True
    assert report["sound"] is False
    assert report["flagged"][0]["channel"] == "container_removed"


def test_recording_a_run_without_a_code_revision_is_refused(test_client) -> None:
    """Placement against a later meaning change cannot be recovered, so it is required now."""
    response = test_client.post("/runs", json={"tenant": "hpml", "item": "x"})

    assert response.status_code == 422


def test_recording_an_outcome_without_naming_its_scorer_is_refused(test_client) -> None:
    """A label whose provenance is unknown can be neither cited nor trained on."""
    response = test_client.post("/runs", json=_payload(item="task-9", resolved=True))

    assert response.status_code == 422
    assert "label_source" in response.text


def test_recording_an_outcome_with_its_scorer_is_accepted(test_client) -> None:
    response = test_client.post(
        "/runs",
        json=_payload(
            item="task-10",
            resolved=True,
            label_source=LabelSource.OFFICIAL_HARNESS.value,
        ),
    )

    assert response.status_code == 201
