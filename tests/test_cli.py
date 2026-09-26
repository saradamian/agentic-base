"""Behavioural tests for `agentic-base check`.

The exit-code contract is the CLI's whole point — it is what lets the command gate a CI job —
so each code has a test that earns it: 0 only for a sound verdict the check could actually have
flagged, 1 for not sound, and 2 for everything the input could not answer, including input the
command could not read. All in-process through `main`, which is also what the console script
calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_base.cli import main
from agentic_base.domain.validity import check_comparison, report_as_dict

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "inspect"


def _uneven(tmp_path: Path) -> Path:
    """The uneven-timeout scenario: arm b times out on 12 of 40 items, arm a on none."""
    lines = []
    for n in range(40):
        lines.append(json.dumps({"item": f"t{n}", "arm": "a", "resolved": True}))
        channel = {"channel": "timeout"} if n < 12 else {"resolved": False}
        lines.append(json.dumps({"item": f"t{n}", "arm": "b", **channel}))
    path = tmp_path / "uneven.jsonl"
    path.write_text("\n".join(lines))
    return path


def _even(tmp_path: Path) -> Path:
    """Two arms of 210 runs, 10 timeouts each: enough data for a clean sound verdict."""
    lines = []
    for arm in ("a", "b"):
        for n in range(210):
            row: dict[str, object] = {"item": f"t{n}", "arm": arm}
            row.update({"channel": "timeout"} if n >= 200 else {"resolved": True})
            lines.append(json.dumps(row))
    path = tmp_path / "even.jsonl"
    path.write_text("\n".join(lines))
    return path


def test_an_uneven_comparison_exits_1_and_prints_flow_verdict_and_citability(
    tmp_path, capsys
) -> None:
    code = main(["check", str(_uneven(tmp_path))])

    out = capsys.readouterr().out
    assert code == 1
    assert "a: assessed 40; excluded 0 (none); analysed 40" in out
    assert "b: assessed 40; excluded 12 (12 timeout); analysed 28" in out
    assert "not sound: timeout: 30.0% (b) vs 0.0% (a)" in out
    assert "outcomes: 0 name a citable scorer, 0 diagnostic, 68 name none" in out


def test_a_sound_comparison_the_check_could_have_flagged_exits_0(
    tmp_path, capsys
) -> None:
    code = main(["check", str(_even(tmp_path))])

    assert code == 0
    assert capsys.readouterr().out.startswith("a: assessed 210")


def test_too_little_data_exits_2_not_0(tmp_path, capsys) -> None:
    """A verdict the input never earned must not read as a green in CI."""
    lines = [json.dumps({"item": "t0", "arm": "a", "channel": "timeout"})]
    for n in range(1, 5):
        lines.append(json.dumps({"item": f"t{n}", "arm": "a", "resolved": True}))
    for n in range(5):
        lines.append(json.dumps({"item": f"t{n}", "arm": "b", "resolved": True}))
    path = tmp_path / "tiny.jsonl"
    path.write_text("\n".join(lines))

    code = main(["check", str(path)])

    assert code == 2
    assert "inconclusive: too little data" in capsys.readouterr().out


def test_a_single_arm_exits_2(tmp_path, capsys) -> None:
    path = tmp_path / "one_arm.jsonl"
    path.write_text(json.dumps({"item": "t0", "arm": "a", "resolved": True}))

    code = main(["check", str(path)])

    assert code == 2
    assert "cannot produce a finding" in capsys.readouterr().out


def test_a_path_that_does_not_exist_exits_2_and_says_why(tmp_path, capsys) -> None:
    code = main(["check", str(tmp_path / "absent.jsonl")])

    assert code == 2
    assert "cannot read" in capsys.readouterr().err


def test_a_file_the_adapter_cannot_parse_exits_2_and_names_the_line(
    tmp_path, capsys
) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text("not json\n")

    code = main(["check", str(path)])

    assert code == 2
    assert "line 1" in capsys.readouterr().err


def test_an_empty_input_exits_2_rather_than_passing_on_nothing(
    tmp_path, capsys
) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")

    code = main(["check", str(path)])

    assert code == 2
    assert "no records" in capsys.readouterr().err


def test_json_output_reuses_report_as_dict(tmp_path, capsys) -> None:
    path = _uneven(tmp_path)

    code = main(["check", str(path), "--json"])

    document = json.loads(capsys.readouterr().out)
    from agentic_base.adapters import from_jsonl

    expected = report_as_dict(check_comparison(from_jsonl(path)))
    assert code == 1
    assert {k: v for k, v in document.items() if k != "citability"} == expected
    assert document["citability"]["unattributed"] == 68


def test_field_mapping_flags_reach_the_adapter(tmp_path, capsys) -> None:
    path = tmp_path / "renamed.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {"task": f"t{n}", "config": arm, "score": 1, "scored_by": "human"}
            )
            for n in range(3)
            for arm in ("a", "b")
        )
    )

    code = main(
        [
            "check",
            str(path),
            "--arm",
            "config",
            "--item",
            "task",
            "--verdict",
            "score",
            "--scorer",
            "scored_by",
        ]
    )

    out = capsys.readouterr().out
    assert code == 2, "no exclusion anywhere means the check had nothing to test"
    assert "outcomes: 6 name a citable scorer" in out


def test_inspect_logs_are_read_by_suffix_and_compare_as_arms(capsys) -> None:
    code = main(
        ["check", str(FIXTURES / "baseline.json"), str(FIXTURES / "planner.json")]
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "demo/baseline: assessed 6; excluded 0 (none); analysed 6" in out
    assert "demo/planner: assessed 6; excluded 4" in out
    assert "not sound: any_exclusion" in out


def test_jsonl_arms_may_arrive_as_one_file_each(tmp_path, capsys) -> None:
    for arm in ("a", "b"):
        rows = [
            json.dumps({"item": f"t{n}", "arm": arm, "resolved": True})
            for n in range(3)
        ]
        if arm == "b":
            rows.append(json.dumps({"item": "t3", "arm": "b", "channel": "timeout"}))
        (tmp_path / f"{arm}.jsonl").write_text("\n".join(rows))

    code = main(["check", str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")])

    out = capsys.readouterr().out
    assert code == 2, "one timeout in four runs is not a finding either way"
    assert "a: assessed" in out
    assert "b: assessed" in out


def test_the_command_without_arguments_is_an_argparse_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert excinfo.value.code == 2, (
        "argparse's own 2 matches the unusable-input contract"
    )


def test_the_console_script_is_declared_so_an_install_gets_the_command() -> None:
    text = (ROOT / "pyproject.toml").read_text()

    assert 'agentic-base = "agentic_base.cli:main"' in text


def test_format_jsonl_reads_json_lines_whatever_the_file_is_called(
    tmp_path, capsys
) -> None:
    renamed = tmp_path / "uneven.json"
    renamed.write_text(_uneven(tmp_path).read_text())

    assert main(["check", str(renamed)]) == 2
    assert "--format jsonl" in capsys.readouterr().err

    assert main(["check", "--format", "jsonl", str(renamed)]) == 1
