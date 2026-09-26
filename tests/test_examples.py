"""The examples run, and print exactly what their output files and the README show.

An example nobody runs is prose, and prose has no positive control. Each example is executed as a
reader would run it, and its output is compared with the file committed beside it, so a change
that alters what a user sees fails here instead of in someone's terminal.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _normalised(text: str, base_url: str = "") -> str:
    """Remove what differs by install and by machine: the package version and the port."""
    if base_url:
        text = text.replace(base_url, "http://localhost:8080")
    return re.sub(r"agentic-base \S+ patterns", "agentic-base <version> patterns", text)


def _run(script: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        [sys.executable, str(EXAMPLES / script)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), **(env or {})},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_the_library_example_prints_what_its_output_file_shows() -> None:
    expected = (EXAMPLES / "is_this_comparison_sound.out").read_text()

    assert _run("is_this_comparison_sound.py") == expected


def test_the_check_cli_prints_what_its_output_file_shows(capsys) -> None:
    """The README's front-door command, run as a reader would run it."""
    from agentic_base.cli import main

    code = main(["check", str(EXAMPLES / "results.jsonl"), "--arm", "config"])

    assert capsys.readouterr().out == (EXAMPLES / "results.out").read_text()
    assert code == 1, (
        "the committed example is the not-sound case, and 1 is its exit code"
    )


@pytest.fixture(scope="module")
def service_url(tmp_path_factory) -> Iterator[str]:
    """A real service on a free port, as a reader would start it."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path_factory.mktemp('examples') / 'runs.db'}",
        "REDACTION": "patterns",
        "OTEL_SDK_DISABLED": "true",
        # As deployed: tokens required, one covering the examples' tenants and the citable
        # scorers their labels name.
        "AUTH": "tokens",
        "API_TOKENS": '{"example-token-0000001": {"tenants": ["example-team", '
        '"platform-team"], "label_sources": ["official_harness", "human"]}}',
    }
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--app-dir",
            str(ROOT / "src"),
            "agentic_base.main:get_app",
            "--factory",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                httpx.get(
                    f"{base_url}/runs/integrity", params={"tenant": "x"}, timeout=1
                )
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "the service did not start"
                time.sleep(0.2)
        yield base_url
    finally:
        server.terminate()
        server.wait(timeout=30)


@pytest.mark.parametrize("script", ["record_and_ask", "service_agent"])
def test_a_service_example_prints_what_its_output_file_shows(
    service_url, script
) -> None:
    printed = _run(f"{script}.py", {"AGENTIC_BASE_URL": service_url})

    assert _normalised(printed, service_url) == (EXAMPLES / f"{script}.out").read_text()


def test_the_pages_show_the_output_the_examples_print() -> None:
    pages = {
        "README.md": ("results.out", "is_this_comparison_sound.out"),
        "docs/service.md": ("record_and_ask.out", "service_agent.out"),
    }
    for page, outputs in pages.items():
        text = (ROOT / page).read_text()
        for name in outputs:
            assert (EXAMPLES / name).read_text() in text, f"{page} does not show {name}"
