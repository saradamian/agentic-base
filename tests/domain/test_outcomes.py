"""The outcome rules, exercised against a record type that is not ours.

That is the whole claim of this module. `agentic-env` keeps its own row, in SQLite, inside task
containers, and will not exchange it for a Postgres model; if the rules only applied to our table
they would not travel, and the discipline is the part that was supposed to travel.

So the fixture here is a bare dataclass with no relationship to `RunRecord`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentic_base.domain.outcomes import (
    LabelAuthority,
    LabelSource,
    RunRecordCreate,
    RunStatus,
    authority_of,
    exclusion_channel,
    is_citable,
    is_excluded,
    mlflow_source_type,
)


@dataclass
class ForeignRecord:
    """A consumer's own row. Structurally judgeable, otherwise unrelated to this package."""

    status: RunStatus = RunStatus.COMPLETED
    failure_kind: str = ""
    resolved: bool | None = True
    label_source: LabelSource = LabelSource.OFFICIAL_HARNESS
    degraded: bool = False


def test_a_foreign_record_labelled_by_the_authoritative_harness_is_citable() -> None:
    assert is_citable(ForeignRecord())


def test_a_foreign_record_labelled_by_a_convenience_checker_is_not_citable() -> None:
    record = ForeignRecord(label_source=LabelSource.CONVENIENCE_VERIFIER)
    assert not is_citable(record)


def test_a_foreign_record_the_agent_graded_itself_is_not_citable() -> None:
    assert not is_citable(ForeignRecord(label_source=LabelSource.SELF_REPORTED))


def test_a_verdict_from_a_degraded_instrument_is_not_citable_however_authoritative() -> (
    None
):
    assert not is_citable(ForeignRecord(degraded=True))


def test_an_unlabelled_foreign_record_is_not_citable() -> None:
    record = ForeignRecord(resolved=None, label_source=LabelSource.UNLABELLED)
    assert not is_citable(record)


def test_a_completed_foreign_record_stays_in_its_denominator() -> None:
    assert not is_excluded(ForeignRecord())
    assert exclusion_channel(ForeignRecord()) == "included"


def test_a_failed_run_is_a_measurement_and_stays_in_the_denominator() -> None:
    """Failing is an outcome. Only the run not happening is an exclusion."""
    assert not is_excluded(ForeignRecord(status=RunStatus.FAILED, resolved=False))


def test_an_infrastructure_error_leaves_the_denominator_by_its_named_channel() -> None:
    record = ForeignRecord(
        status=RunStatus.INFRASTRUCTURE_ERROR, failure_kind="container_removed"
    )
    assert is_excluded(record)
    assert exclusion_channel(record) == "container_removed"


def test_an_exclusion_with_no_detail_falls_back_to_its_status() -> None:
    assert exclusion_channel(ForeignRecord(status=RunStatus.TIMEOUT)) == "timeout"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (LabelSource.UNLABELLED, LabelAuthority.NONE),
        (LabelSource.SELF_REPORTED, LabelAuthority.DIAGNOSTIC),
        (LabelSource.CONVENIENCE_VERIFIER, LabelAuthority.DIAGNOSTIC),
        (LabelSource.OFFICIAL_HARNESS, LabelAuthority.AUTHORITATIVE),
        (LabelSource.HUMAN, LabelAuthority.AUTHORITATIVE),
    ],
)
def test_every_source_declares_an_authority(
    source: LabelSource, expected: LabelAuthority
) -> None:
    assert authority_of(source) is expected


def test_the_two_code_scorers_differ_in_authority_while_sharing_a_modality() -> None:
    """The reason this vocabulary exists beside MLflow's rather than instead of it.

    Both are `CODE` to a modality taxonomy. They disagreed on a measured corpus in both
    directions, so which of them a result may quote is not recoverable from the modality.
    """
    convenience = LabelSource.CONVENIENCE_VERIFIER
    official = LabelSource.OFFICIAL_HARNESS
    assert mlflow_source_type(convenience) == mlflow_source_type(official) == "CODE"
    assert authority_of(convenience) is not authority_of(official)


def test_a_service_agents_own_feedback_is_recorded_and_not_citable() -> None:
    """A person's thumbs-up and a model's score are worth keeping and are not measurements."""
    assert authority_of(LabelSource.USER_FEEDBACK) is LabelAuthority.DIAGNOSTIC
    assert authority_of(LabelSource.MODEL_JUDGE) is LabelAuthority.DIAGNOSTIC
    assert authority_of(LabelSource.HUMAN) is LabelAuthority.AUTHORITATIVE
    assert mlflow_source_type(LabelSource.USER_FEEDBACK) == "HUMAN"
    assert mlflow_source_type(LabelSource.MODEL_JUDGE) == "LLM_JUDGE"


def test_the_facet_schema_lists_every_label_source() -> None:
    import json
    from pathlib import Path

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs/schemas/OutcomeRunFacet.json"
        ).read_text()
    )
    listed = schema["properties"]["labelSource"]["enum"]

    assert sorted(listed) == sorted(s.value for s in LabelSource)


def test_every_source_maps_onto_an_mlflow_source_type() -> None:
    for source in LabelSource:
        assert mlflow_source_type(source) in {"HUMAN", "LLM_JUDGE", "CODE"}


def test_recording_an_outcome_without_naming_its_scorer_is_refused() -> None:
    with pytest.raises(ValueError, match="label_source"):
        RunRecordCreate(tenant="hpml", code_revision="abc123", resolved=True)


def test_a_run_may_be_recorded_with_no_outcome_at_all() -> None:
    """Labelling later is legitimate. Labelling anonymously is not."""
    payload = RunRecordCreate(tenant="hpml", code_revision="abc123")
    assert payload.resolved is None
    assert payload.label_source is LabelSource.UNLABELLED


def test_a_failure_detail_on_a_completed_run_is_refused() -> None:
    with pytest.raises(ValueError, match="failure_kind"):
        RunRecordCreate(
            tenant="hpml", code_revision="abc123", failure_kind="timeout@7200"
        )


def test_tenant_and_code_revision_have_no_defaults() -> None:
    """Optional provenance is not supplied, which is why neither of these is optional."""
    with pytest.raises(ValueError):
        RunRecordCreate(code_revision="abc123")
    with pytest.raises(ValueError):
        RunRecordCreate(tenant="hpml")


def test_a_benchmarks_own_grader_is_authoritative_and_citable() -> None:
    """tau, Terminal-Bench and ARE ship a grader and no separate harness; their verdict is the
    benchmark's own, and a consumer must not have to file it as a convenience check."""
    from agentic_base.domain.outcomes import (
        CITABLE_LABEL_SOURCES,
        LabelAuthority,
        LabelSource,
        authority_of,
        mlflow_source_type,
    )

    assert LabelSource.BENCHMARK_GRADER in CITABLE_LABEL_SOURCES
    assert authority_of(LabelSource.BENCHMARK_GRADER) is LabelAuthority.AUTHORITATIVE
    assert mlflow_source_type(LabelSource.BENCHMARK_GRADER) == "CODE"


def test_personal_or_health_data_is_refused_on_the_community_tier() -> None:
    """Classification decides the tier; the one combination no regime permits is refused."""
    import pytest

    from agentic_base.domain.outcomes import DataClass, IsolationTier, RunRecordCreate

    with pytest.raises(ValueError, match="community"):
        RunRecordCreate(
            tenant="t",
            code_revision="c",
            classification=DataClass.HEALTH,
            isolation_tier=IsolationTier.COMMUNITY,
        )
    RunRecordCreate(tenant="t", code_revision="c", classification=DataClass.HEALTH)
    RunRecordCreate(
        tenant="t",
        code_revision="c",
        classification=DataClass.HEALTH,
        isolation_tier=IsolationTier.ISOLATED,
    )


def test_a_run_records_who_it_acted_for_and_who_approved_what() -> None:
    from agentic_base.domain.outcomes import Approval, RunRecordCreate

    run = RunRecordCreate(
        tenant="t",
        code_revision="c",
        principal="alice@example.org",
        approvals=[
            Approval(
                action="git push",
                decision="approved",
                by="alice@example.org",
                at="2026-09-13T10:00:00Z",
            )
        ],
    )

    assert run.principal == "alice@example.org"
    assert run.approvals[0].decision == "approved"
    assert run.redaction == "none"


def test_a_run_records_whether_the_person_was_told_and_the_output_marked() -> None:
    """Article 50 applies since 2 August 2026. The telling happens in a channel this layer does
    not own, so the record carries the claim and the means, defaulting to none."""
    plain = RunRecordCreate(tenant="t", code_revision="abc")

    assert plain.disclosure == "none"
    assert plain.content_marking == "none"

    told = RunRecordCreate(
        tenant="t",
        code_revision="abc",
        disclosure="channel-notice",
        content_marking="c2pa:urn:uuid:1234",
    )

    assert told.disclosure == "channel-notice"
    assert told.content_marking == "c2pa:urn:uuid:1234"
