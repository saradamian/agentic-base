"""Behavioural tests for the log adapters.

The Inspect fixtures under `tests/fixtures/inspect/` are hand-written against the documented
log schema (`version: 2`), not produced by inspect_ai, which cannot be installed on the
library's dependency floor. The `.eval` variant is committed as its readable parts
(`eval_parts/header.json`, `eval_parts/samples/*.json`) and zipped by a fixture, so the archive
layout the reader targets is visible in review rather than opaque bytes in git.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agentic_base.adapters import (
    NO_VERDICT,
    LogObservation,
    citability,
    from_inspect_log,
    from_jsonl,
)
from agentic_base.domain.outcomes import LabelSource
from agentic_base.domain.validity import INCLUDED, NEVER_ATTEMPTED, check_comparison

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "inspect"


@pytest.fixture()
def eval_zip(tmp_path) -> Path:
    """The committed `.eval` parts, archived the way inspect_ai lays the zip out."""
    parts = FIXTURES / "eval_parts"
    path = tmp_path / "epochs.eval"
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(parts / "header.json", "header.json")
        for sample in sorted((parts / "samples").glob("*.json")):
            archive.write(sample, f"samples/{sample.name}")
    return path


def test_reads_rows_with_the_default_field_names(tmp_path) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text(
        json.dumps({"item": "t1", "arm": "a", "resolved": True})
        + "\n\n"  # blank lines are tolerated
        + json.dumps({"item": "t2", "arm": "a", "channel": "timeout"})
        + "\n"
    )

    observations = from_jsonl(path)

    assert observations == [
        LogObservation("t1", "a", INCLUDED, resolved=True),
        LogObservation("t2", "a", "timeout"),
    ]


def test_field_names_are_configurable() -> None:
    lines = [json.dumps({"task": 7, "config": "deep", "score": 1, "status": ""})]

    (obs,) = from_jsonl(
        lines, item="task", arm="config", verdict="score", channel="status"
    )

    assert obs == LogObservation("7", "deep", INCLUDED, resolved=True)


def test_a_row_with_no_verdict_is_an_exclusion_not_an_analysed_run() -> None:
    """POSITIVE CONTROL for the module's one shared rule: a record nobody scored must never
    land in the analysed population, where the check could not see its absence."""
    lines = [json.dumps({"item": "t1", "arm": "a"})]

    (obs,) = from_jsonl(lines)

    assert obs.channel == NO_VERDICT
    assert obs.resolved is None


def test_a_verdict_the_adapter_cannot_read_lands_in_the_same_channel() -> None:
    lines = [json.dumps({"item": "t1", "arm": "a", "resolved": {"weird": "shape"}})]

    (obs,) = from_jsonl(lines)

    assert obs.channel == NO_VERDICT


@pytest.mark.parametrize(
    ("value", "resolved"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        (1.0, True),
        (0.5, False),  # partial credit is not a resolve
        ("true", True),
        ("FAIL", False),
        ("C", True),
        ("P", False),
        # a numeric string reads as its number
        pytest.param("0.5", False, id="numeric-string"),
    ],
)
def test_the_verdict_shapes_logs_actually_hold_are_read(value, resolved) -> None:
    (obs,) = from_jsonl([json.dumps({"item": "t", "arm": "a", "resolved": value})])

    assert obs.channel == INCLUDED
    assert obs.resolved is resolved


def test_a_row_naming_an_exclusion_channel_is_excluded_even_with_a_verdict() -> None:
    lines = [
        json.dumps({"item": "t1", "arm": "a", "channel": "timeout", "resolved": True})
    ]

    (obs,) = from_jsonl(lines)

    assert obs.channel == "timeout"
    assert obs.resolved is None, "a verdict on an excluded run counts toward nothing"


def test_an_explicit_included_channel_still_needs_a_verdict() -> None:
    (obs,) = from_jsonl([json.dumps({"item": "t1", "arm": "a", "channel": "included"})])

    assert obs.channel == NO_VERDICT


def test_a_malformed_line_is_an_error_naming_the_line() -> None:
    lines = [json.dumps({"item": "t1", "arm": "a", "resolved": True}), "not json"]

    with pytest.raises(ValueError, match="line 2"):
        from_jsonl(lines)


def test_a_line_that_is_not_an_object_is_an_error_naming_the_line() -> None:
    with pytest.raises(ValueError, match="line 1.*list"):
        from_jsonl(["[1, 2]"])


def test_a_known_scorer_name_maps_into_the_vocabulary() -> None:
    lines = [
        json.dumps(
            {
                "item": "t",
                "arm": "a",
                "resolved": True,
                "label_source": "official_harness",
            }
        )
    ]

    (obs,) = from_jsonl(lines)

    assert obs.label_source is LabelSource.OFFICIAL_HARNESS
    assert obs.scorer == "official_harness"


def test_an_unknown_scorer_name_grants_no_authority_and_is_kept_verbatim() -> None:
    lines = [
        json.dumps(
            {"item": "t", "arm": "a", "resolved": True, "label_source": "my_checker"}
        )
    ]

    (obs,) = from_jsonl(lines)

    assert obs.label_source is LabelSource.UNLABELLED
    assert obs.scorer == "my_checker"


def test_adapted_rows_feed_the_validity_check() -> None:
    """POSITIVE CONTROL end to end: uneven timeouts written as plain JSONL must come out of
    `check_comparison` as an unsound contrast."""
    lines = []
    for n in range(40):
        lines.append(json.dumps({"item": f"t{n}", "arm": "a", "resolved": True}))
        if n < 12:
            lines.append(
                json.dumps({"item": f"t{n}", "arm": "b", "channel": "timeout"})
            )
        else:
            lines.append(json.dumps({"item": f"t{n}", "arm": "b", "resolved": False}))

    report = check_comparison(from_jsonl(lines))

    assert not report.sound
    assert [c.channel for c in report.flagged] == ["timeout"]


def test_citability_buckets_outcomes_by_the_authority_of_their_scorer() -> None:
    observations = [
        LogObservation("t1", "a", INCLUDED, True, "h", LabelSource.OFFICIAL_HARNESS),
        LogObservation("t2", "a", INCLUDED, True, "me", LabelSource.SELF_REPORTED),
        LogObservation("t3", "a", INCLUDED, False),
        LogObservation("t4", "a", "timeout"),  # no verdict: counted nowhere
    ]

    summary = citability(observations)

    assert (summary.citable, summary.diagnostic, summary.unattributed) == (1, 1, 1)
    assert summary.describe() == (
        "outcomes: 1 name a citable scorer, 1 diagnostic, 1 name none"
    )


def test_citability_says_so_when_nothing_carries_a_verdict() -> None:
    assert citability([LogObservation("t", "a", "timeout")]).describe() == (
        "outcomes: none carry a verdict"
    )


def test_reads_the_documented_inspect_json_format() -> None:
    observations = from_inspect_log(FIXTURES / "planner.json")

    assert {o.arm for o in observations} == {"demo/planner"}
    assert {o.item: o.channel for o in observations} == {
        "s1#e1": INCLUDED,
        "s2#e1": INCLUDED,
        "s3#e1": "error",
        "s4#e1": "token_limit",
        "s5#e1": NO_VERDICT,
        "s6#e1": NEVER_ATTEMPTED,
    }


def test_an_inspect_score_reads_as_the_verdict_and_names_its_scorer() -> None:
    observations = {o.item: o for o in from_inspect_log(FIXTURES / "planner.json")}

    assert observations["s1#e1"].resolved is True
    assert observations["s2#e1"].resolved is False
    assert observations["s1#e1"].scorer == "match"
    assert observations["s1#e1"].label_source is LabelSource.UNLABELLED, (
        "Inspect records no scorer authority, so none may be assumed"
    )


def test_a_sample_the_dataset_declares_but_never_ran_is_an_exclusion() -> None:
    """POSITIVE CONTROL: absence is the largest exclusion channel there is, and the log's own
    dataset declaration is what states the denominator."""
    observations = from_inspect_log(FIXTURES / "planner.json")

    assert [o.item for o in observations if o.channel == NEVER_ATTEMPTED] == ["s6#e1"]


def test_epochs_are_one_observation_each_keyed_so_pairing_works(eval_zip) -> None:
    observations = from_inspect_log(eval_zip)

    assert [(o.item, o.resolved) for o in observations] == [
        ("s1#e1", True),
        ("s1#e2", False),
        ("s2#e1", False),  # a 0.5 is partial credit, not a resolve
    ]


def test_the_arm_can_come_from_the_task_or_a_metadata_key() -> None:
    by_task = from_inspect_log(FIXTURES / "planner.json", arm="task")
    by_metadata = from_inspect_log(FIXTURES / "planner.json", arm="variant")

    assert {o.arm for o in by_task} == {"demo_task"}
    assert {o.arm for o in by_metadata} == {"planner"}


def test_an_arm_key_the_log_does_not_carry_is_an_error_not_an_empty_arm() -> None:
    with pytest.raises(ValueError, match="no arm named 'nonexistent'"):
        from_inspect_log(FIXTURES / "planner.json", arm="nonexistent")


def test_a_json_file_that_is_not_an_inspect_log_is_refused(tmp_path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"rows": []}))

    with pytest.raises(ValueError, match="no top-level 'eval' object"):
        from_inspect_log(path)


def test_two_inspect_logs_compare_as_arms() -> None:
    observations = from_inspect_log(FIXTURES / "baseline.json") + from_inspect_log(
        FIXTURES / "planner.json"
    )

    report = check_comparison(observations)

    assert report.arms_examined == 2
    assert report.flow["demo/baseline"].analysed == 6
    assert report.flow["demo/planner"].analysed == 2
    assert not report.sound, "the pooled exclusion rate, 4/6 vs 0/6, is a real gap"


@pytest.mark.parametrize("missing", ["item", "arm"])
def test_a_row_without_an_item_or_arm_is_an_error_naming_the_line(missing) -> None:
    row = {"item": "t1", "arm": "a", "resolved": True}
    del row[missing]
    lines = [json.dumps({"item": "t0", "arm": "a", "resolved": True}), json.dumps(row)]

    with pytest.raises(ValueError, match=f"line 2: no '{missing}' field"):
        from_jsonl(lines)


def test_json_lines_under_a_json_name_is_refused_with_the_way_out(tmp_path) -> None:
    path = tmp_path / "results.json"
    path.write_text('{"item": "t0", "arm": "a"}\n{"item": "t1", "arm": "a"}\n')

    with pytest.raises(ValueError, match="--format jsonl"):
        from_inspect_log(path)
