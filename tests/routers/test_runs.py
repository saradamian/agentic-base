"""End-to-end tests for the run endpoints."""

import json

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


def test_a_run_is_served_as_prov_json_with_its_scorer_attributed(test_client) -> None:
    created = test_client.post("/runs", json=_payload(item="task-prov")).json()
    test_client.post(
        f"/runs/{created['run_id']}/label",
        json={"resolved": True, "label_source": LabelSource.OFFICIAL_HARNESS.value},
    )

    response = test_client.get(
        f"/runs/{created['run_id']}/provenance", params={"format": "prov"}
    )

    assert response.status_code == 200
    doc = response.json()
    (outcome,) = [v for k, v in doc["entity"].items() if k.endswith("/outcome")]
    assert outcome["ab:authority"] == "authoritative"
    assert "wasAttributedTo" in doc


def test_a_run_is_served_as_an_openlineage_event(test_client) -> None:
    created = test_client.post(
        "/runs", json=_payload(item="task-ol", arm="full")
    ).json()

    response = test_client.get(
        f"/runs/{created['run_id']}/provenance", params={"format": "openlineage"}
    )

    assert response.status_code == 200
    event = response.json()
    assert event["job"]["namespace"] == "hpml"
    assert event["run"]["facets"]["agenticBaseOutcome"]["authority"] == "none"


def test_a_run_is_served_as_a_process_run_crate(test_client) -> None:
    created = test_client.post("/runs", json=_payload(item="task-crate")).json()

    response = test_client.get(
        f"/runs/{created['run_id']}/provenance", params={"format": "rocrate"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/ld+json")
    graph = {e["@id"]: e for e in response.json()["@graph"]}
    assert graph[f"#{created['run_id']}"]["@type"] == "CreateAction"


def test_provenance_of_an_unknown_run_is_not_found(test_client) -> None:
    assert test_client.get("/runs/nope/provenance").status_code == 404


def test_an_unknown_provenance_format_is_refused(test_client) -> None:
    created = test_client.post("/runs", json=_payload(item="task-fmt")).json()

    response = test_client.get(
        f"/runs/{created['run_id']}/provenance", params={"format": "csv"}
    )

    assert response.status_code == 422


def test_an_approval_is_kept_beside_the_run(test_client) -> None:
    created = test_client.post("/runs", json=_payload(item="task-approve")).json()

    response = test_client.post(
        f"/runs/{created['run_id']}/approvals",
        json={
            "action": "git push",
            "decision": "approved",
            "by": "alice@example.org",
            "at": "2026-09-13T10:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["approvals"][0]["by"] == "alice@example.org"
    fetched = test_client.get(f"/runs/{created['run_id']}").json()
    assert len(fetched["approvals"]) == 1


def test_a_health_run_on_the_community_tier_is_refused_at_the_api(test_client) -> None:
    response = test_client.post(
        "/runs",
        json=_payload(
            item="task-health", classification="health", isolation_tier="community"
        ),
    )

    assert response.status_code == 422


class _Marker:
    instrument = "marker 1.0"

    def redact(self, text):
        from agentic_base.redaction import Redacted

        return Redacted(
            text=text.replace("Maria", "<PERSON>"),
            found={"PERSON": text.count("Maria")},
        )


def test_a_configured_redactor_runs_before_the_transcript_is_written(
    app, test_client
) -> None:
    from agentic_base.redaction.configured import get_redactor

    app.dependency_overrides[get_redactor] = _Marker
    try:
        created = test_client.post(
            "/runs",
            json=_payload(
                item="redact-1", messages=[{"role": "user", "content": "hi Maria"}]
            ),
        ).json()
    finally:
        app.dependency_overrides.pop(get_redactor)

    stored = test_client.get(f"/runs/{created['run_id']}").json()
    assert stored["messages"] == [{"role": "user", "content": "hi <PERSON>"}]
    assert stored["redaction"] == "marker 1.0"


def test_without_a_redactor_the_transcript_is_written_as_sent(test_client) -> None:
    created = test_client.post(
        "/runs",
        json=_payload(
            item="redact-2", messages=[{"role": "user", "content": "hi Maria"}]
        ),
    ).json()

    stored = test_client.get(f"/runs/{created['run_id']}").json()
    assert stored["messages"] == [{"role": "user", "content": "hi Maria"}]
    assert stored["redaction"] == "none"


class _Unavailable:
    instrument = "patterns + llm m"

    def redact(self, text):
        from agentic_base.redaction import RedactionUnavailable

        raise RedactionUnavailable("llm: the endpoint answered HTTP 503")

    def patterns_only(self):
        return _Marker()


def _post_with(app, test_client, redactor, **body):
    from agentic_base.redaction.configured import get_redactor

    app.dependency_overrides[get_redactor] = lambda: redactor
    try:
        return test_client.post(
            "/runs",
            json=_payload(messages=[{"role": "user", "content": "hi Maria"}], **body),
        )
    finally:
        app.dependency_overrides.pop(get_redactor)


def test_a_run_is_refused_when_no_name_detector_can_run(app, test_client) -> None:
    response = _post_with(
        app, test_client, _Unavailable(), item="redact-3", classification="internal"
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert "not recorded" in response.json()["detail"]


def test_a_public_run_falls_back_to_patterns_and_says_so(app, test_client) -> None:
    response = _post_with(
        app, test_client, _Unavailable(), item="redact-4", classification="public"
    )

    assert response.status_code == 201
    assert response.json()["redaction"] == "marker 1.0"


def test_the_validity_report_carries_the_per_arm_flow_it_rests_on(test_client) -> None:
    """A verdict without its accounting cannot be checked by the reader it is meant to convince."""
    for item in ("t1", "t2"):
        test_client.post("/runs", json=_payload(tenant="flowing", item=item, arm="a"))
        test_client.post(
            "/runs",
            json=_payload(tenant="flowing", item=item, arm="b", status="timeout"),
        )

    report = test_client.get(
        "/runs/validity/report", params={"tenant": "flowing"}
    ).json()

    assert [(f["arm"], f["assessed"], f["analysed"]) for f in report["flow"]] == [
        ("a", 2, 2),
        ("b", 2, 0),
    ]
    assert report["flow"][1]["excluded"] == {"timeout": 2}


def _export(test_client, tenant):
    response = test_client.get("/runs/export", params={"tenant": tenant})
    lines = [line for line in response.text.splitlines() if line.strip()]
    return response, json.loads(lines[0]), [json.loads(line) for line in lines[1:]]


def test_a_tenant_can_take_its_whole_corpus_in_one_request(test_client) -> None:
    """The Data Act's switching right needs a way out that does not go through us."""
    for item in ("task-1", "task-2"):
        test_client.post("/runs", json=_payload(item=item, tenant="leaving"))
    test_client.post("/runs", json=_payload(item="task-3", tenant="staying"))

    response, manifest, records = _export(test_client, "leaving")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert manifest["tenant"] == "leaving" and manifest["records"] == 2
    assert [r["record"]["item"] for r in records] == ["task-1", "task-2"]
    assert all(r["record"]["tenant"] == "leaving" for r in records)


def test_the_manifest_counts_what_follows_so_a_truncated_file_is_visible(
    test_client,
) -> None:
    test_client.post("/runs", json=_payload(item="task-1", tenant="counted"))

    _, manifest, records = _export(test_client, "counted")

    assert manifest["records"] == len(records)


def test_an_exported_run_can_be_written_back(test_client) -> None:
    """The export is in the shape the write path accepts, which is what makes it portable."""
    test_client.post(
        "/runs",
        json=_payload(
            item="task-1",
            tenant="portable",
            messages=[{"role": "user", "content": "hi"}],
        ),
    )

    _, _, records = _export(test_client, "portable")
    replayed = test_client.post("/runs", json=records[0]["record"])

    assert replayed.status_code == 201
    assert replayed.json()["messages"] == [{"role": "user", "content": "hi"}]


def test_an_exported_run_says_which_run_it_is_and_when_in_utc(test_client) -> None:
    """Without the id and the time an export cannot answer what ran when, and a replay would
    stamp every run with the moment it was replayed."""
    created = test_client.post("/runs", json=_payload(tenant="dated")).json()

    _, _, records = _export(test_client, "dated")

    assert records[0]["run_id"] == created["run_id"]
    assert records[0]["created_at"].endswith(("+00:00", "Z"))
    assert (
        test_client.get(f"/runs/{created['run_id']}")
        .json()["created_at"]
        .endswith(("+00:00", "Z"))
    )


def test_a_tenant_with_nothing_recorded_exports_an_empty_corpus(test_client) -> None:
    response, manifest, records = _export(test_client, "nobody")

    assert response.status_code == 200
    assert manifest["records"] == 0 and records == []
