"""The tool contract.

This is the root of everything tool-shaped: a registry, a protocol surface, a filesystem backend
all speak in these types. In the framework this came from, 45 files import it, which is why it
moves before anything that depends on it.

Two decisions carried across deliberately.

`ToolResult.ok` and `ToolResult.fail` rather than exceptions for ordinary failure. A tool that
cannot do its job has produced a result the model can read and act on; only an unusable
environment is exceptional.

Tool names are the identity, and two backends implementing the same capability register the same
name. A filesystem on a host and a filesystem inside a container both expose `read_file`. Telemetry
then aggregates across backends without a translation table, and there is no later moment at which
that becomes possible if the names diverged at the start.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agentic_base.limits import get_limits


class FatalToolError(Exception):
    """The tool's environment is unusable, so the whole run should stop.

    Distinct from an ordinary failure, which a caller retries. This says retrying is pointless:
    the container backing a filesystem was removed, so every later call fails identically. A
    dispatcher re-raises this instead of turning it into a failed result, so a caller terminates
    rather than spending its remaining budget on a dead call.
    """


@runtime_checkable
class ScopedBackend(Protocol):
    """A backend whose reachable paths can be widened at runtime.

    Declared as a capability rather than a base class on purpose. In the framework this came from,
    the equivalent scan tested for a concrete class, silently skipped a second implementation that
    behaved identically, and every cross-product read failed with a path error for months. A
    protocol cannot be satisfied by accident and cannot be missed by inheritance.
    """

    def add_allowed_root(self, path: str) -> None: ...


@dataclass
class ToolResult:
    """What a tool hands back."""

    success: bool
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.output if self.success else f"Error: {self.error}"

    @classmethod
    def ok(cls, output: str, **metadata: Any) -> ToolResult:
        return cls(success=True, output=output, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> ToolResult:
        return cls(success=False, error=error, metadata=metadata)


@dataclass
class ToolParameter:
    """One parameter, as the model will be shown it."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    enum: list[str] | None = None
    default: Any = None
    items: dict[str, Any] | None = None

    def to_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = self.enum
        if self.items is not None:
            schema["items"] = self.items
        return schema


@dataclass
class Tool:
    """A tool a model can call."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    handler: Callable[..., Awaitable[ToolResult]] | Callable[..., ToolResult] | None = (
        None
    )
    category: str = "general"

    max_output_chars: int | None = None
    """What one call may return to the model. None takes the configured default.

    A capability limit as much as a storage one: raising it changes what the model can see, so two
    runs at different values are not comparable. It reads from configuration rather than carrying
    a literal, so a deployment can move it and a record can say what it was.
    """

    backend: Any = field(default=None, repr=False, compare=False)
    """The filesystem or sandbox this tool is bound to, when it has one.

    Set by whatever factory builds the tool. A caller that needs to widen reachable paths selects
    on the `ScopedBackend` capability, never on a class. Excluded from comparison because it is
    wiring, not identity.
    """

    @property
    def output_limit(self) -> int:
        return self.max_output_chars or get_limits().tool_output_max_chars

    def to_openai_schema(self) -> dict[str, Any]:
        """The function-calling schema, as an OpenAI-compatible endpoint expects it."""
        properties = {p.name: p.to_schema() for p in self.parameters}
        required = [p.name for p in self.parameters if p.required]
        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": properties},
            },
        }
        if required:
            schema["function"]["parameters"]["required"] = required
        return schema
