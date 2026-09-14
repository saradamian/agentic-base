"""Is this comparison sound? The library half, on your own record type, no service needed.

Two configurations of an agent attempt the same twenty tasks. The one with a planner looks far
better, but it also times out on the six hardest tasks, and a timeout has no verdict. Scoring
only the runs that finished rewards it for failing on the tasks it could not do.

    pip install surf-agentic-base
    python examples/is_this_comparison_sound.py
"""

from __future__ import annotations

from dataclasses import dataclass

from agentic_base.domain.outcomes import (
    LabelSource,
    RunStatus,
    exclusion_channel,
    is_citable,
)
from agentic_base.domain.validity import check_comparison, paired_items, render_flow


@dataclass
class MyRun:
    """Whatever your project already stores. The rules only need these attributes."""

    item: str
    arm: str
    status: RunStatus
    resolved: bool | None = None
    label_source: LabelSource = LabelSource.OFFICIAL_HARNESS
    degraded: bool = False
    failure_kind: str = ""

    @property
    def channel(self) -> str:
        return exclusion_channel(self)


def build_runs() -> list[MyRun]:
    tasks = [f"task-{n:02d}" for n in range(1, 21)]
    runs = []
    for n, task in enumerate(tasks, start=1):
        # baseline: times out on the hardest task, resolves the first ten
        if n == 20:
            runs.append(MyRun(task, "baseline", RunStatus.TIMEOUT))
        else:
            runs.append(MyRun(task, "baseline", RunStatus.COMPLETED, resolved=n <= 10))
        # with-planner: times out on the six hardest tasks, resolves the first twelve
        if n >= 15:
            runs.append(MyRun(task, "with-planner", RunStatus.TIMEOUT))
        else:
            runs.append(
                MyRun(task, "with-planner", RunStatus.COMPLETED, resolved=n <= 12)
            )
    return runs


def rate(
    runs: list[MyRun], arm: str, *, items: set[str] | None = None, finished_only: bool
) -> str:
    chosen = [r for r in runs if r.arm == arm and (items is None or r.item in items)]
    if finished_only:
        chosen = [r for r in chosen if r.channel == "included"]
    solved = sum(1 for r in chosen if r.resolved)
    return f"{solved}/{len(chosen)} = {solved / len(chosen):.1%}"


def main() -> None:
    runs = build_runs()

    print("1. The number people report: resolved, over runs that finished")
    for arm in ("baseline", "with-planner"):
        print(f"   {arm:13} {rate(runs, arm, finished_only=True)}")

    report = check_comparison(runs)
    print()
    print("2. What the validity check says")
    print(f"   {report.summary()}")
    print(
        f"   examined {report.observations_examined} runs, {report.arms_examined} arms,"
        f" {report.channels_examined} exclusion channel(s); could have flagged: {report.could_have_flagged}"
    )
    print()
    print("3. The per-arm flow the verdict rests on")
    for line in render_flow(report.flow).splitlines():
        print(f"   {line}")

    both = paired_items(runs)
    print()
    print("4. Two honest numbers instead of one flattering one")
    print("   every run, a timeout counted as unresolved:")
    for arm in ("baseline", "with-planner"):
        print(f"   {arm:13} {rate(runs, arm, finished_only=False)}")
    print(f"   only the {len(both)} tasks both arms finished:")
    for arm in ("baseline", "with-planner"):
        print(f"   {arm:13} {rate(runs, arm, items=both, finished_only=True)}")

    print()
    print("5. Which verdicts may be cited")
    for label, source, degraded in (
        ("the benchmark's own harness", LabelSource.OFFICIAL_HARNESS, False),
        ("a quick in-tree check", LabelSource.CONVENIENCE_VERIFIER, False),
        ("the harness, but it failed open", LabelSource.OFFICIAL_HARNESS, True),
        ("the agent grading itself", LabelSource.SELF_REPORTED, False),
    ):
        run = MyRun("task-01", "baseline", RunStatus.COMPLETED, True, source, degraded)
        print(f"   {label:34} citable: {is_citable(run)}")


if __name__ == "__main__":
    main()
