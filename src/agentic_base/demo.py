"""The uneven-timeout trap, demonstrated by an installed package with nothing else at hand:

    python -m agentic_base.demo

Ships inside the wheel rather than under ``examples/`` because the reader it is for has run
``pip install surf-agentic-base`` and has no checkout. It generates the scenario in memory as
the JSONL rows ``agentic-base check`` reads, prints the flattering number people report, and
then prints exactly what the command says about the same rows — the same rendering, through
`agentic_base.cli.check_text`, not a paraphrase of it.
"""

from __future__ import annotations

import json

from agentic_base.adapters import LogObservation, from_jsonl
from agentic_base.cli import check_text
from agentic_base.domain.validity import INCLUDED


def build_lines() -> list[str]:
    """Forty runs over twenty tasks, as JSONL. The planner arm resolves more of the runs that
    finish — and times out on the six hardest tasks, where a timeout has no verdict."""
    lines = []
    for n in range(1, 21):
        task = f"task-{n:02d}"
        if n == 20:
            lines.append(
                json.dumps({"item": task, "arm": "baseline", "channel": "timeout"})
            )
        else:
            lines.append(
                json.dumps(
                    {
                        "item": task,
                        "arm": "baseline",
                        "resolved": n <= 10,
                        "label_source": "official_harness",
                    }
                )
            )
        if n >= 15:
            lines.append(
                json.dumps({"item": task, "arm": "with-planner", "channel": "timeout"})
            )
        else:
            lines.append(
                json.dumps(
                    {
                        "item": task,
                        "arm": "with-planner",
                        "resolved": n <= 12,
                        "label_source": "official_harness",
                    }
                )
            )
    return lines


def naive_rate(observations: list[LogObservation], arm: str) -> str:
    """Resolved over runs that finished: the number people report."""
    finished = [o for o in observations if o.arm == arm and o.channel == INCLUDED]
    solved = sum(1 for o in finished if o.resolved)
    return f"{solved}/{len(finished)} = {solved / len(finished):.1%}"


def main() -> int:
    """Print the naive number, then the checked verdict. Returns 0: the demonstration
    succeeded; the 1 it prints is what ``agentic-base check`` would exit with."""
    observations = from_jsonl(build_lines())
    print("Two configurations attempt the same twenty tasks. One times out on the")
    print("six hardest, and a timeout has no verdict.")
    print()
    print("1. The number people report: resolved, over runs that finished")
    for arm in ("baseline", "with-planner"):
        print(f"   {arm:13} {naive_rate(observations, arm)}")
    print()
    print("2. What `agentic-base check` says about the same rows")
    text, code = check_text(observations)
    for line in text.splitlines():
        print(f"   {line}")
    print()
    print(
        f"exit code {code}: the flattering number is not a claim these logs can carry"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
