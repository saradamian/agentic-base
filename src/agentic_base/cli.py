"""``agentic-base check``: the two checks, over logs the caller already has.

No server, database or token: the command reads eval results from disk — JSONL, CSV with a
header row, or an Inspect AI ``.eval``/``.json`` log — through `agentic_base.adapters`, runs
`check_comparison` over them, and prints the CONSORT-style per-arm flow, the verdict line and a
citability line. With ``--baseline`` it also says how large each arm's difference from that
arm is and how sure that is (`agentic_base.domain.contrast`). The exit code carries the
validity verdict, with or without ``--baseline``, so the command gates a CI job:

* **0** — sound, and the check could have flagged something: at least two arms, at least one
  exclusion channel, every difference inside an interval narrow enough to have caught a gap.
* **1** — not sound: some exclusion channel's rate differs across arms beyond what the
  interval and the absolute floor allow.
* **2** — the input could not answer either way: too little data for the interval to call,
  fewer than two arms, no exclusion channel anywhere (a check with nothing to test has not
  been passed), or a path the command could not read.

A green that was never able to go red gets cited, so 0 is reserved for the first case and
everything unanswerable is 2, never 0.

``agentic-base calls`` reads back the calls tool servers built on the library recorded
(`agentic_base.recording`): per tool, how often it was called, how often it failed and how long
it took, and with ``--failures`` each failed call with its arguments and error. It exits 0 when
it could read what it was given, an empty log included, and 2 when it could not.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentic_base.adapters import (
    LogObservation,
    citability,
    from_csv,
    from_inspect_log,
    from_jsonl,
)
from agentic_base.domain.contrast import contrast_against, contrast_as_dict
from agentic_base.domain.validity import (
    ValidityReport,
    check_comparison,
    render_flow,
    report_as_dict,
)
from agentic_base.recording import (
    CallLog,
    CallSummary,
    default_call_log_directory,
    read_call_log,
    summarise_calls,
)

_EXIT_CODES = "exit codes: 0 sound, 1 not sound, 2 inconclusive or unreadable input"

INSPECT_SUFFIXES = (".eval", ".json")
"""Paths with these suffixes are read as Inspect AI logs; everything else as JSONL."""

CSV_SUFFIXES = (".csv",)
"""Paths with these suffixes are read as CSV with a header row."""


def exit_code(report: ValidityReport) -> int:
    """The verdict as a process exit code; the module docstring is the contract."""
    if not report.sound:
        return 1
    return 0 if report.could_have_flagged else 2


def check_text(
    observations: Iterable[LogObservation], *, baseline: str | None = None
) -> tuple[str, int]:
    """The human-readable verdict block and its exit code, for these observations.

    One function rather than print statements in `main`, so `agentic_base.demo` shows exactly
    what the command would say instead of a paraphrase of it. With a `baseline`, every other
    arm's contrast against it follows the verdict line; the exit code is the verdict's either
    way, because the contrast describes a comparison and does not decide whether to trust it.
    """
    observations = list(observations)
    report = check_comparison(observations)
    contrasts = (
        [c.describe() for c in contrast_against(observations, baseline=baseline)]
        if baseline is not None
        else []
    )
    lines = [
        render_flow(report.flow),
        report.summary(),
        *contrasts,
        citability(observations).describe(),
    ]
    return "\n".join(line for line in lines if line), exit_code(report)


def _load(path: Path, args: argparse.Namespace) -> list[LogObservation]:
    fmt = getattr(args, "format", "auto")
    if fmt == "inspect" or (fmt == "auto" and path.suffix in INSPECT_SUFFIXES):
        return from_inspect_log(path, arm=args.arm or "model")
    reader = from_jsonl
    if fmt == "csv" or (fmt == "auto" and path.suffix in CSV_SUFFIXES):
        reader = from_csv
    return reader(
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
    arms = sorted({obs.arm for obs in observations})
    if args.baseline is not None and args.baseline not in arms:
        print(
            f"no runs for baseline {args.baseline!r}; arms present: {', '.join(arms)}",
            file=sys.stderr,
        )
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
        if args.baseline is not None:
            document["contrasts"] = [
                contrast_as_dict(c)
                for c in contrast_against(observations, baseline=args.baseline)
            ]
        print(json.dumps(document, indent=2))
        return exit_code(report)
    text, code = check_text(observations, baseline=args.baseline)
    print(text)
    return code


def _since(value: str) -> datetime:
    """``7d``, ``12h`` or a date such as ``2026-10-01``, as the moment it names in UTC."""
    now = datetime.now(timezone.utc)
    try:
        if value.endswith("d"):
            return now - timedelta(days=float(value[:-1]))
        if value.endswith("h"):
            return now - timedelta(hours=float(value[:-1]))
        when = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a number of days (7d), hours (12h) or a date (2026-10-01)"
        ) from None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _shown(path: Path) -> str:
    """A path as a person would type it: the home directory as ``~``."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except (ValueError, RuntimeError):
        return str(path)


def _minute(time: str) -> str:
    return time[:16].replace("T", " ")


def calls_text(log: CallLog, summary: CallSummary, where: str) -> str:
    """The table `agentic-base calls` prints, one row per server and tool."""
    if not summary.tools:
        return (
            f"No calls recorded in {where}. A tool server built on agentic-base writes one line "
            "there for each call an agent makes."
        )
    servers = len({t.server for t in summary.tools})
    first, last = _minute(summary.first), _minute(summary.last)
    period = f"at {first}" if first == last else f"{first} to {last}"
    lines = [
        f"{summary.calls} call{'s' * (summary.calls != 1)} to {servers} "
        f"server{'s' * (servers != 1)}, {period} UTC, in {where}",
        "",
    ]
    rows = [("server", "tool", "calls", "failed", "median ms", "p95 ms")]
    rows += [
        (
            t.server,
            t.tool,
            f"{t.calls}",
            f"{t.failed}",
            f"{t.median_ms:,.0f}",
            f"{t.p95_ms:,.0f}",
        )
        for t in summary.tools
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        left = [cell.ljust(widths[i]) for i, cell in enumerate(row[:2])]
        right = [cell.rjust(widths[i + 2]) for i, cell in enumerate(row[2:])]
        lines.append("  ".join(left + right).rstrip())
    if summary.clients:
        clients = ", ".join(
            f"{name} ({count})" for name, count in summary.clients.items()
        )
        lines += ["", f"clients: {clients}"]
    if log.unreadable_lines:
        lines.append(
            f"{log.unreadable_lines} line(s) could not be read and were skipped."
        )
    if summary.failed:
        lines += [
            "",
            "agentic-base calls --failures shows each failed call with its arguments.",
        ]
    return "\n".join(lines)


def _latest_failures(
    calls: list[dict[str, object]], limit: int
) -> list[dict[str, object]]:
    failed = [c for c in calls if not c.get("success")]
    return failed[max(0, len(failed) - limit) :]


def failures_text(calls: list[dict[str, object]], limit: int) -> str:
    """The latest *limit* failed calls, newest last: when, where, the arguments and the error."""
    failed = _latest_failures(calls, limit)
    if not failed:
        return "No failed calls."
    lines = []
    for call in failed:
        arguments = json.dumps(call.get("arguments", {}), ensure_ascii=False)
        lines.append(
            f"{_minute(str(call.get('time', '')))}  {call.get('server', '')}  "
            f"{call.get('tool', '')}  {arguments}"
        )
        lines.append(f"  {call.get('error') or 'failed, no error text recorded'}")
    return "\n".join(lines)


def _calls(args: argparse.Namespace) -> int:
    try:
        log = read_call_log(args.paths, since=args.since, server=args.server)
    except OSError as error:
        print(
            f"cannot read {error.filename or error}: {error.strerror or error}",
            file=sys.stderr,
        )
        return 2
    summary = summarise_calls(log.calls)
    if len(args.paths) == 1:
        where = _shown(Path(args.paths[0]))
    elif args.paths:
        where = f"{len(log.files)} files"
    else:
        where = _shown(default_call_log_directory())
    if args.json:
        document: dict[str, object] = {
            "files": [str(f) for f in log.files],
            "calls": summary.calls,
            "failed": summary.failed,
            "unreadable_lines": log.unreadable_lines,
            "first": summary.first,
            "last": summary.last,
            "tools": [asdict(t) for t in summary.tools],
            "clients": summary.clients,
        }
        if args.failures:
            document["failures"] = _latest_failures(log.calls, args.limit)
        print(json.dumps(document, indent=2, default=str))
        return 0
    print(
        failures_text(log.calls, args.limit)
        if args.failures
        else calls_text(log, summary, where)
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``agentic-base`` console script."""
    parser = argparse.ArgumentParser(
        prog="agentic-base",
        description=(
            "The library's checks over eval logs you already have, and the calls your tool "
            "servers recorded."
        ),
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
    check.add_argument(
        "paths", nargs="+", help="JSONL or CSV files and/or Inspect logs"
    )
    check.add_argument(
        "--arm",
        default=None,
        help="JSONL/CSV: the field holding the arm (default 'arm'); "
        "Inspect: 'model' (default), 'task', or a metadata key",
    )
    check.add_argument(
        "--item", default="item", help="JSONL/CSV field holding the unit of work"
    )
    check.add_argument(
        "--verdict", default="resolved", help="JSONL/CSV field holding the outcome"
    )
    check.add_argument(
        "--channel",
        default="channel",
        help="JSONL/CSV field naming how a run left the denominator",
    )
    check.add_argument(
        "--scorer",
        default="label_source",
        help="JSONL/CSV field naming who decided the outcome",
    )
    check.add_argument(
        "--format",
        choices=("auto", "jsonl", "csv", "inspect"),
        default="auto",
        help="how to read the paths; 'auto' (default) reads .eval and .json as Inspect "
        "logs, .csv as CSV with a header row, and anything else as JSONL",
    )
    check.add_argument(
        "--baseline",
        default=None,
        help="an arm to compare every other arm against: prints the difference, its 95%% "
        "interval, McNemar's exact test and bounds that assume nothing about excluded runs",
    )
    check.add_argument(
        "--json", action="store_true", help="print the report as JSON instead of text"
    )
    check.set_defaults(handler=_check)
    calls = commands.add_parser(
        "calls",
        help="what agents did with your tool servers",
        description=(
            "Reads the call log that tool servers built on agentic-base write, by default every "
            "month's file in ~/.local/state/agentic-base/calls, and prints per tool how often it "
            "was called, how often it failed and how long it took."
        ),
        epilog="exit codes: 0 read (an empty log included), 2 a path could not be read",
    )
    calls.add_argument(
        "paths",
        nargs="*",
        help="call log files or directories (default: the directory servers write to)",
    )
    calls.add_argument(
        "--since",
        type=_since,
        default=None,
        help="only calls after this: 7d, 12h or a date such as 2026-10-01",
    )
    calls.add_argument("--server", default=None, help="only this server's calls")
    calls.add_argument(
        "--failures",
        action="store_true",
        help="list the failed calls with their arguments and errors instead of the table",
    )
    calls.add_argument(
        "--limit",
        type=int,
        default=20,
        help="how many of the latest failed calls --failures shows (default 20)",
    )
    calls.add_argument(
        "--json", action="store_true", help="print the summary as JSON instead of text"
    )
    calls.set_defaults(handler=_calls)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
