"""Declare a tool by decorating the function that implements it."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from agentic_base.tools.types import Tool, ToolParameter

_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def tool(
    name: str | None = None,
    description: str | None = None,
    category: str = "general",
    parameters: dict[str, dict[str, Any]] | None = None,
    max_output_chars: int | None = None,
) -> Callable[[Callable[..., Any]], Tool]:
    """Turn a function into a `Tool`.

    The name defaults to the function's name and the description to the first line of its
    docstring. Parameters come from the signature: the type hint gives the JSON type and a
    default makes the parameter optional. An entry in *parameters* replaces what the signature
    would give for that parameter.
    """
    overrides = parameters or {}

    def decorator(fn: Callable[..., Any]) -> Tool:
        hints = get_type_hints(fn)
        params: list[ToolParameter] = []
        for param_name, param in inspect.signature(fn).parameters.items():
            if param_name in ("self", "cls"):
                continue
            has_default = param.default is not inspect.Parameter.empty
            if param_name in overrides:
                override = overrides[param_name]
                params.append(
                    ToolParameter(
                        name=param_name,
                        type=override.get("type", "string"),
                        description=override.get("description", ""),
                        required=override.get("required", not has_default),
                        enum=override.get("enum"),
                        default=param.default if has_default else None,
                    )
                )
                continue
            params.append(
                ToolParameter(
                    name=param_name,
                    type=_JSON_TYPES.get(hints.get(param_name, str), "string"),
                    description=param_name.replace("_", " "),
                    required=not has_default,
                    default=param.default if has_default else None,
                )
            )

        kwargs: dict[str, Any] = {
            "name": name or fn.__name__,
            "description": description
            or (fn.__doc__ or "").strip().split("\n")[0]
            or fn.__name__,
            "parameters": params,
            "handler": fn,
            "category": category,
        }
        if max_output_chars is not None:
            kwargs["max_output_chars"] = max_output_chars
        return Tool(**kwargs)

    return decorator
