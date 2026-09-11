"""The seam between a served call and whatever records it."""

from __future__ import annotations

from typing import Any

import pytest

from app.recording import CallObserver, NullObserver, SafeObserver


class _Recording:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {**arguments, "seen": True}

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        return f"[wrapped]{result}"

    def record(self, tool, arguments, result, success, elapsed_ms, **extra) -> None:
        self.calls.append((tool, success))


class _Broken:
    def inspect_arguments(self, tool, arguments):
        raise RuntimeError("database is gone")

    def inspect_result(self, tool, result, success):
        raise RuntimeError("exporter is gone")

    def record(self, tool, arguments, result, success, elapsed_ms, **extra):
        raise RuntimeError("journal is gone")


def test_the_default_observer_changes_nothing() -> None:
    observer = NullObserver()

    assert observer.inspect_arguments("t", {"a": 1}) == {"a": 1}
    assert observer.inspect_result("t", "out", True) == "out"
    assert observer.record("t", {}, "out", True, 1.0) is None


def test_the_default_observer_satisfies_the_protocol() -> None:
    """A host that implements nothing still type-checks as an observer."""
    assert isinstance(NullObserver(), CallObserver)


def test_a_host_observer_can_alter_arguments_and_results() -> None:
    observer = _Recording()

    assert observer.inspect_arguments("t", {"a": 1})["seen"] is True
    assert observer.inspect_result("t", "out", True).startswith("[wrapped]")


def test_a_failed_call_is_recorded_like_any_other() -> None:
    """A wrapper that records only successes produces a corpus with a zero failure rate, which is
    the most confidently wrong number a corpus can hold."""
    observer = _Recording()

    observer.record("t", {}, "boom", False, 30_000.0)

    assert observer.calls == [("t", False)]


def test_a_broken_host_observer_cannot_break_a_tool_call() -> None:
    """The call is the work; the record is the account of it. Inverting that is the wrong trade."""
    safe = SafeObserver(_Broken())

    assert safe.inspect_arguments("t", {"a": 1}) == {"a": 1}
    assert safe.inspect_result("t", "out", True) == "out"
    safe.record("t", {}, "out", True, 1.0)

    assert safe.failures == 3


def test_a_quietly_broken_recorder_is_visible_as_a_count(caplog) -> None:
    """Degrading silently is how a corpus ends up empty and nobody notices."""
    safe = SafeObserver(_Broken())

    for _ in range(4):
        safe.record("t", {}, "out", True, 1.0)

    assert safe.failures == 4


def test_a_working_observer_never_increments_the_failure_count() -> None:
    safe = SafeObserver(_Recording())

    safe.record("t", {}, "out", True, 1.0)

    assert safe.failures == 0
