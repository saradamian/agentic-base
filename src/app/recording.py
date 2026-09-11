"""The seam between a served tool call and whatever records it.

Serving tools over a protocol bypasses an application's own runtime, so journal recording, trace
capture and injection defence do not happen unless something puts them back. In the predecessor
framework that something is a single chokepoint every call routes through, and it is the reason
served traffic becomes learnable corpus rather than requests that merely succeeded. Measured
there: 67 recorded calls carrying session, call index, tool name, journal identifier and input
threat level, one of them a failed thirty-second call, which is exactly the case a wrapper without
a chokepoint drops silently.

That chokepoint is not a primitive. It reaches into a journal, a trace store, a lineage recorder,
an OpenTelemetry bridge and two security modules. Importing it into a base layer would drag all of
that across and the layer would stop being thin.

So the layer declares the seam and the host fills it. An application with nothing to record gets
the no-op and pays nothing. An application with a journal supplies one object and gets its
telemetry back.

Two rules the no-op encodes, both learned expensively.

A failed call is recorded. A wrapper that records successes produces a corpus whose failure rate
is zero, which is the most confidently wrong number a corpus can contain.

Nothing here may raise. A telemetry failure that breaks a tool call has inverted the priority: the
call is the work and the record is the account of it.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CallObserver(Protocol):
    """What a host implements to see served tool calls.

    Every method has a no-op default in `NullObserver`, so a host implements only what it has
    somewhere to put.
    """

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Called before dispatch. Returns the arguments to use.

        A host may scan for injected instructions here. It should not block on finding them: a
        wiki page that legitimately contains "ignore previous instructions" is a security runbook,
        and refusing to read it is a worse failure than reading it as data.
        """
        ...

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        """Called after dispatch. Returns the result to hand back.

        A host may wrap external content in a data boundary here, so the model receives it as data
        rather than as instruction.
        """
        ...

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        """Called once per call, successful or not."""
        ...


class NullObserver:
    """The default. Sees everything, keeps nothing, never raises."""

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        return result

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        return None


class SafeObserver:
    """Wraps a host's observer so its failures cannot reach the caller.

    A host's recorder touches a database, a network exporter, or a model. Any of those can fail,
    and none of those failures should turn a working tool call into an error. On failure the
    wrapper degrades to the no-op behaviour and counts it, so a recorder that is quietly broken is
    visible as a count rather than as an absence.
    """

    def __init__(self, inner: CallObserver) -> None:
        self._inner = inner
        self.failures = 0

    def inspect_arguments(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._inner.inspect_arguments(tool, arguments)
        except Exception:
            self.failures += 1
            return arguments

    def inspect_result(self, tool: str, result: str, success: bool) -> str:
        try:
            return self._inner.inspect_result(tool, result, success)
        except Exception:
            self.failures += 1
            return result

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        elapsed_ms: float,
        **extra: Any,
    ) -> None:
        try:
            self._inner.record(tool, arguments, result, success, elapsed_ms, **extra)
        except Exception:
            self.failures += 1
