"""Getting a value back out of a batch job's stdout.

A batch job's only universal channel back to whoever submitted it is standard output, and on a
real cluster that stream is not yours. Module loads, library deprecation warnings, and every
other rank's output are interleaved with whatever you printed. So "run this remotely and give me
a value back" degrades into grepping prose out of a log tail, and a caller ends up parsing a
number that was actually part of a warning with no way to tell.

Three properties, each of which is load-bearing.

Delimited, so a reader can find the payload without knowing anything about the job.

One line of base64. This is the part that is easy to get wrong. Pretty-printed JSON spanning
several lines is split down the middle the moment another rank writes between them, and the
reader sees a syntax error instead of a value. A single base64 line has no interior newline for
anything to interleave into, and its alphabet cannot be confused with log text.

Absent, present, or corrupt, and never two of those. A block that is there but unreadable,
because the job was killed part way through writing it, is reported as corrupt. Treating an
unreadable result as no result manufactures a plausible answer out of a measurement failure.

The emitting half is stdlib only and self-contained, because it runs inside whatever environment
the job happens to have, which is usually one where this package is not installed.
"""

from __future__ import annotations

import base64
import binascii
import enum
import json
from dataclasses import dataclass
from typing import Any

RESULT_START = "###JOB_RESULT_START###"
RESULT_END = "###JOB_RESULT_END###"

EMIT_SNIPPET = f'''
def emit_job_result(value):
    """Print a structured result for the submitter to recover from stdout."""
    import base64 as _b64, json as _json, sys as _sys

    _sys.stdout.flush()
    print("{RESULT_START}")
    print(_b64.b64encode(_json.dumps(value).encode("utf-8")).decode("ascii"))
    print("{RESULT_END}")
    _sys.stdout.flush()
'''
"""Paste into a generated or hand-written job script. Imports nothing outside the standard
library and defines no module-level state, so it is safe to splice in anywhere."""


class ResultState(str, enum.Enum):
    ABSENT = "absent"
    """No block in the output. The job did not emit one."""

    OK = "ok"
    CORRUPT = "corrupt"
    """A block was there and could not be read. The result existed and was lost, which calls for
    a different response than a job that returned nothing."""


@dataclass(frozen=True)
class JobResult:
    state: ResultState
    value: Any = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state is ResultState.OK


def encode_result(
    value: Any, *, start: str = RESULT_START, end: str = RESULT_END
) -> str:
    """The exact text a job should print, markers included.

    The markers are parameters because a consumer that adopted this protocol before this
    package existed has jobs in flight that print its own, and a reader that only knows ours
    would report those results absent. The default is the protocol; the parameter is the
    migration.
    """
    payload = base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")
    return f"{start}\n{payload}\n{end}"


def parse_result(
    text: str, *, start: str = RESULT_START, end: str = RESULT_END
) -> JobResult:
    """Recover a result from arbitrary job output.

    The last complete block wins, because a job may emit progress results before its final one.
    Inside the block, the one line that decodes is the payload: another rank writing a log line
    into the middle of the block is the case this protocol exists for, and it must not turn a
    result that was printed correctly into a corrupt one. Only a block where nothing decodes is
    reported corrupt.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == start]
    if not starts:
        return JobResult(ResultState.ABSENT, detail="no result block in output")

    first = starts[-1]
    ends = [i for i, line in enumerate(lines) if line.strip() == end and i > first]
    if not ends:
        return JobResult(
            ResultState.CORRUPT,
            detail="result block opened and never closed, output was probably truncated",
        )

    body = [line.strip() for line in lines[first + 1 : ends[0]] if line.strip()]
    if not body:
        return JobResult(ResultState.CORRUPT, detail="result block was empty")

    # Each line on its own, last first, then the whole body joined for a payload that a wrapper
    # split across lines. The first candidate that is both base64 and JSON is the result.
    last_detail = "no line in the result block decoded as base64-encoded JSON"
    for candidate in [*reversed(body), "".join(body)]:
        try:
            decoded = base64.b64decode(candidate, validate=True)
        except (binascii.Error, ValueError) as exc:
            last_detail = f"payload is not valid base64 ({exc})"
            continue
        try:
            return JobResult(ResultState.OK, value=json.loads(decoded.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_detail = f"payload is not valid JSON ({exc})"
    return JobResult(ResultState.CORRUPT, detail=last_detail)
