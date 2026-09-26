"""``agentic-base check``: the two checks, over logs the caller already has.

No server, database or token: the command reads eval results from disk — JSONL, or an Inspect
AI ``.eval``/``.json`` log — through `agentic_base.adapters`, runs `check_comparison` over
them, and prints the CONSORT-style per-arm flow, the verdict line and a citability line. The
exit code carries the verdict so the command gates a CI job:

* **0** — sound, and the check could have flagged something: at least two arms, at least one
  exclusion channel, every difference inside an interval narrow enough to have caught a gap.
* **1** — not sound: some exclusion channel's rate differs across arms beyond what the
  interval and the absolute floor allow.
* **2** — the input could not answer either way: too little data for the interval to call,
  fewer than two arms, no exclusion channel anywhere (a check with nothing to test has not
  been passed), or a path the command could not read.

A green that was never able to go red gets cited, so 0 is reserved for the first case and
everything unanswerable is 2, never 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from agentic_base.adapters import (
    LogObservation,
    citability,
    from_inspect_log,
    from_jsonl,
)
from agentic_base.domain.validity import (
    ValidityReport,
    check_comparison,
    render_flow,
    report_as_dict,
)

_EXIT_CODES = "exit codes: 0 sound, 1 not sound, 2 inconclusive or unreadable input"

INSPECT_SUFFIXES = (".eval", ".json")
"""Paths with these suffixes are read as Inspect AI logs; everything else as JSONL."""


def exit_code(report: ValidityReport) -> int:
    """The verdict as a process exit code; the module docstring is the contract."""
    if not report.sound:
        return 1
    return 0 if report.could_have_flagged else 2


def check_text(observations: Iterable[LogObservation]) -> tuple[str, int]:
    """The human-readable verdict block and its exit code, for these observations.

    One function rather than print statements in `main`, so `agentic_base.demo` shows exactly
    what the command would say instead of a paraphrase of it.
    """
    observations = list(observations)
    report = check_comparison(observations)
    lines = [
        render_flow(report.flow),
        report.summary(),
        citability(observations).describe(),
    ]
    return "\n".join(line for line in lines if line), exit_code(report)


def _load(path: Path, args: argparse.Namespace) -> list[LogObservation]:
    fmt = getattr(args, "format", "auto")
    if fmt == "inspect" or (fmt == "auto" and path.suffix in INSPECT_SUFFIXES):
        return from_inspect_log(path, arm=args.arm or "model")
    return from_jsonl(
        path,
        item=args.item,
        arm=args.arm or "arm",
        verdict=args.verdict,
        channel=args.channel,
        scorer=args.scorer,
    )


def _check(args: argparse.Namespace) -> int:
    observations: list[LogObservation] = []
    for name in args.paths:
        path = Path(name)
        try:
            observations.extend(_load(path, args))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"cannot read {path}: {error}", file=sys.stderr)
            return 2
    if not observations:
        print("the input holds no records", file=sys.stderr)
        return 2
    if args.json:
        report = check_comparison(observations)
        summary = citability(observations)
        document = report_as_dict(report)
        document["citability"] = {
            "citable": summary.citable,
            "diagnostic": summary.diagnostic,
            "unattributed": summary.unattributed,
            "description": summary.describe(),
        }
        print(json.dumps(document, indent=2))
        return exit_code(report)
    text, code = check_text(observations)
    print(text)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``agentic-base`` console script."""
    parser = argparse.ArgumentParser(
        prog="agentic-base",
        description="The library's checks, over eval logs you already have.",
        epilog=_EXIT_CODES,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check",
        help="is this comparison sound, and who scored what",
        description=(
            "Reads JSONL results (one JSON object per line; the field-name flags say where "
            "to look) or Inspect AI .eval/.json logs (where --arm is 'model', 'task' or a "
            "metadata key), and adjudicates the comparison across arms."
        ),
        epilog=_EXIT_CODES,
    )
    check.add_argument("paths", nargs="+", help="JSONL files and/or Inspect logs")
    check.add_argument(
        "--arm",
        default=None,
        help="JSONL: the field holding the arm (default 'arm'); "
        "Inspect: 'model' (default), 'task', or a metadata key",
    )
    check.add_argument(
        "--item", default="item", help="JSONL field holding the unit of work"
    )
    check.add_argument(
        "--verdict", default="resolved", help="JSONL field holding the outcome"
    )
    check.add_argument(
        "--channel",
        default="channel",
        help="JSONL field naming how a run left the denominator",
    )
    check.add_argument(
        "--scorer",
        default="label_source",
        help="JSONL field naming who decided the outcome",
    )
    check.add_argument(
        "--format",
        choices=("auto", "jsonl", "inspect"),
        default="auto",
        help="how to read the paths; 'auto' (default) reads .eval and .json as Inspect "
        "logs and anything else as JSONL",
    )
    check.add_argument(
        "--json", action="store_true", help="print the report as JSON instead of text"
    )
    check.set_defaults(handler=_check)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
