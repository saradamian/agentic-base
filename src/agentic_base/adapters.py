"""Eval logs someone already has, read into the shape the validity check takes.

`domain.validity.check_comparison` accepts anything with `item`, `arm` and `channel`, and
`domain.outcomes` says which verdicts may be cited. Both are useless to an engineer whose
results live in a JSONL file or an Inspect AI eval log unless something maps those records onto
that shape, so this module does the mapping: standard library only, no service, no database, no
new dependency, because the whole point of the front door is that it opens on the library's own
3.10 four-dependency floor.

Two readers:

* :func:`from_jsonl` reads one JSON object per line, with the field names as arguments because
  nobody's logs agree on them.
* :func:`from_inspect_log` reads an Inspect AI eval log **without importing** ``inspect_ai``
  (which does not install on this library's dependency floor). It targets the log schema at
  ``version: 2``, the format inspect_ai 0.3.x documents and writes: the all-in-one ``.json``
  document, and the ``.eval`` zip whose members are ``header.json`` and
  ``samples/{id}_epoch_{epoch}.json``. The field names were taken from Inspect's published
  log-format documentation, not from running the package, so where a name is uncertain the
  reader tolerates its absence — a missing ``epoch`` reads as 1, a missing ``limit`` type reads
  as the bare channel ``limit``, a header the zip does not carry leaves the eval spec empty —
  rather than guessing a value that would then be analysed.

One rule both readers share, because it closes the gap the recording path can leave open: **a
record whose verdict is missing, or written in a shape the reader cannot interpret, is an
exclusion** (the channel :data:`NO_VERDICT`), never a silently analysed run. Its absence rate is
then checked per arm like any other exclusion channel, which is where uneven missingness shows.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_base.domain.outcomes import LabelAuthority, LabelSource, authority_of
from agentic_base.domain.validity import INCLUDED, NEVER_ATTEMPTED

NO_VERDICT = "no_verdict"
"""Exclusion channel for a record that carries no readable verdict. A run nobody scored left
the denominator as surely as a timeout did, and an uneven rate of them biases a contrast the
same way."""


@dataclass(frozen=True)
class LogObservation:
    """One run, as read from someone else's log.

    Satisfies the `Observation` protocol `check_comparison` takes, and carries the two extra
    fields the citability summary reads. `scorer` keeps the log's own name for whatever decided
    the verdict, verbatim; `label_source` is that name placed in this layer's vocabulary, or
    ``UNLABELLED`` when the name is absent or the vocabulary cannot place it — an unrecognised
    scorer has no established standing, so it grants no authority.
    """

    item: str
    arm: str
    channel: str
    resolved: bool | None = None
    scorer: str = ""
    label_source: LabelSource = LabelSource.UNLABELLED


@dataclass(frozen=True)
class CitabilitySummary:
    """How many outcomes name a citable scorer, a diagnostic one, or none at all."""

    citable: int
    diagnostic: int
    unattributed: int

    def describe(self) -> str:
        total = self.citable + self.diagnostic + self.unattributed
        if total == 0:
            return "outcomes: none carry a verdict"
        return (
            f"outcomes: {self.citable} name a citable scorer, "
            f"{self.diagnostic} diagnostic, {self.unattributed} name none"
        )


def citability(observations: Iterable[LogObservation]) -> CitabilitySummary:
    """Bucket every observation that carries a verdict by the authority of its scorer.

    Excluded observations carry no verdict by construction (see the module rule), so this
    counts analysed runs only. The buckets are `LabelAuthority`'s: authoritative sources are
    citable, diagnostic ones are not, and a run whose scorer is unnamed or unrecognised is
    unattributed — the 43%-empty population that optional provenance produces at scale.
    """
    counts = {authority: 0 for authority in LabelAuthority}
    for obs in observations:
        if obs.resolved is not None:
            counts[authority_of(obs.label_source)] += 1
    return CitabilitySummary(
        citable=counts[LabelAuthority.AUTHORITATIVE],
        diagnostic=counts[LabelAuthority.DIAGNOSTIC],
        unattributed=counts[LabelAuthority.NONE],
    )


_TRUE_WORDS = frozenset({"true", "yes", "pass", "passed", "correct", "resolved", "c"})
_FALSE_WORDS = frozenset(
    {
        "false",
        "no",
        "fail",
        "failed",
        "incorrect",
        "unresolved",
        "i",
        # Inspect's PARTIAL and NOANSWER: partial credit is not a resolve.
        "p",
        "partial",
        "n",
        "noanswer",
    }
)


def _as_verdict(value: Any) -> bool | None:
    """A pass/fail read out of the shapes logs actually hold; ``None`` when it cannot be.

    Booleans are themselves. A number is a resolve only at 1 or above, so partial credit
    (0.5) does not read as resolved. Strings cover the common pass/fail words plus Inspect's
    one-letter values (``C``/``I``/``P``/``N``). Anything else — a dict, an unrecognised
    string — returns ``None``, and the caller treats that as `NO_VERDICT` rather than guess.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value >= 1
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        try:
            return float(lowered) >= 1
        except ValueError:
            return None
    return None


def _as_label_source(name: str) -> LabelSource:
    """The vocabulary's member for this scorer name, or ``UNLABELLED`` when it has none."""
    try:
        return LabelSource(name)
    except ValueError:
        return LabelSource.UNLABELLED


def from_jsonl(
    source: str | Path | Iterable[str],
    *,
    item: str = "item",
    arm: str = "arm",
    verdict: str = "resolved",
    channel: str = "channel",
    scorer: str = "label_source",
) -> list[LogObservation]:
    """Read one JSON object per line into observations the validity check accepts.

    `source` is a path, or an iterable of lines for records already in memory. The keyword
    arguments name the fields, defaulting to this layer's own vocabulary; blank lines are
    skipped, and a line that is not a JSON object raises `ValueError` naming the line number,
    because a silently dropped record is the exact defect the check exists to catch.

    Per row: a non-empty `channel` value other than ``included`` excludes the row through that
    channel, even when the row also carries a verdict — the channel says the run left the
    denominator, and a verdict on an excluded run counts toward nothing. Otherwise the verdict
    field decides: readable (see `_as_verdict`) means analysed; missing or unreadable means the
    `NO_VERDICT` exclusion. The scorer field, when present, is kept verbatim and mapped into
    `LabelSource` for the citability summary.

    A row with no `item` or no `arm` raises `ValueError` naming the line: filed under an empty
    name it would either invent an arm or pair unrelated runs with each other, and either one
    changes the verdict without saying so.
    """
    if isinstance(source, (str, Path)):
        lines: Iterable[str] = Path(source).read_text(encoding="utf-8").splitlines()
    else:
        lines = source
    observations: list[LogObservation] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {number}: not JSON: {error}") from error
        if not isinstance(row, dict):
            raise ValueError(
                f"line {number}: a JSON {type(row).__name__}, not an object"
            )
        item_value = row.get(item)
        arm_value = row.get(arm)
        for field_name, value in ((item, item_value), (arm, arm_value)):
            if value is None or str(value) == "":
                raise ValueError(
                    f"line {number}: no {field_name!r} field — every row needs an item and an "
                    "arm (the --item and --arm flags name the fields)"
                )
        scorer_value = row.get(scorer)
        scorer_name = "" if scorer_value is None else str(scorer_value)
        channel_value = row.get(channel)
        if channel_value not in (None, "", INCLUDED):
            observations.append(
                LogObservation(
                    item=str(item_value),
                    arm=str(arm_value),
                    channel=str(channel_value),
                    scorer=scorer_name,
                    label_source=_as_label_source(scorer_name),
                )
            )
            continue
        resolved = _as_verdict(row.get(verdict))
        observations.append(
            LogObservation(
                item=str(item_value),
                arm=str(arm_value),
                channel=INCLUDED if resolved is not None else NO_VERDICT,
                resolved=resolved,
                scorer=scorer_name,
                label_source=_as_label_source(scorer_name),
            )
        )
    return observations


def _read_inspect_document(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The eval header and the sample list, from either format the schema is written in."""
    if path.suffix == ".eval":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            header: dict[str, Any] = {}
            if "header.json" in names:
                header = json.loads(archive.read("header.json"))
            samples = [
                json.loads(archive.read(name))
                for name in sorted(names)
                if name.startswith("samples/") and name.endswith(".json")
            ]
            return header, samples
    text = path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{path} is not an Inspect eval log ({error}); for JSON Lines results pass "
            "--format jsonl or use a .jsonl name"
        ) from error
    if not isinstance(document, dict) or "eval" not in document:
        raise ValueError(
            f"{path} is not an Inspect eval log: no top-level 'eval' object; for JSON Lines "
            "results pass --format jsonl or use a .jsonl name"
        )
    return document, document.get("samples") or []


def _score_of(sample: dict[str, Any]) -> tuple[bool | None, str]:
    """The verdict and scorer name of a sample's first score, Nones when it has none.

    A sample may carry several scorers; the first in the log's own order is read, which is a
    documented tolerance rather than a choice the schema makes for us.
    """
    scores = sample.get("scores") or {}
    for name, score in scores.items():
        value = score.get("value") if isinstance(score, dict) else score
        return _as_verdict(value), str(name)
    return None, ""


def from_inspect_log(source: str | Path, *, arm: str = "model") -> list[LogObservation]:
    """Read an Inspect AI eval log (``.eval`` zip or ``.json`` document) into observations.

    `arm` says what the contrast is over: ``"model"`` or ``"task"`` read the eval header;
    any other value is a metadata key, looked up on each sample and falling back to the
    header's metadata. A key that resolves nowhere raises rather than filing every run under
    an empty arm.

    The mapping, in the order it is decided per sample: an ``error`` is the ``error`` channel;
    a hit ``limit`` is a channel named for it (``token_limit``, ``time_limit``, ...), counted
    as an exclusion even when the sample was scored afterwards, because the limit and not the
    scorer decided when it ended; a missing or unreadable score is `NO_VERDICT`; the rest are
    analysed. Each epoch is one observation, keyed ``{id}#e{epoch}`` so pairing across arms
    pairs epoch with epoch. Samples the log's dataset declares (``eval.dataset.sample_ids``)
    but never ran become the reserved ``never_attempted`` channel, one per configured epoch —
    the log itself states that denominator, so its absences are counted here rather than left
    to the cross-arm synthesis in `check_comparison`. Inspect records no scorer authority, so
    `label_source` stays ``UNLABELLED`` and the scorer's name rides in `scorer` verbatim.
    """
    path = Path(source)
    header, samples = _read_inspect_document(path)
    spec = header.get("eval") or {}

    def arm_of(sample: dict[str, Any] | None) -> str | None:
        if arm in ("model", "task"):
            value = spec.get(arm)
            return None if value is None else str(value)
        for metadata in (
            (sample or {}).get("metadata") or {},
            spec.get("metadata") or {},
        ):
            if arm in metadata:
                return str(metadata[arm])
        return None

    observations: list[LogObservation] = []
    seen_ids: set[str] = set()
    for sample in samples:
        sample_id = str(sample.get("id"))
        seen_ids.add(sample_id)
        epoch = sample.get("epoch") or 1
        sample_arm = arm_of(sample)
        if sample_arm is None:
            raise ValueError(
                f"{path}: no arm named {arm!r} — use 'model', 'task', or a key present "
                "in the log's metadata"
            )
        item = f"{sample_id}#e{epoch}"
        if sample.get("error") is not None:
            observations.append(LogObservation(item, sample_arm, "error"))
            continue
        limit = sample.get("limit")
        if limit is not None:
            kind = limit.get("type") if isinstance(limit, dict) else None
            observations.append(
                LogObservation(item, sample_arm, f"{kind}_limit" if kind else "limit")
            )
            continue
        resolved, scorer_name = _score_of(sample)
        observations.append(
            LogObservation(
                item,
                sample_arm,
                INCLUDED if resolved is not None else NO_VERDICT,
                resolved=resolved,
                scorer=scorer_name,
            )
        )

    declared = (spec.get("dataset") or {}).get("sample_ids") or []
    never_ran = [str(d) for d in declared if str(d) not in seen_ids]
    if never_ran:
        log_arm = arm_of(None)
        if log_arm is None:
            raise ValueError(
                f"{path}: {len(never_ran)} declared sample(s) never ran and the arm key "
                f"{arm!r} is not in the log's own metadata, so their absence cannot be "
                "attributed to an arm"
            )
        epochs = int((spec.get("config") or {}).get("epochs") or 1)
        for sample_id in never_ran:
            for epoch in range(1, epochs + 1):
                observations.append(
                    LogObservation(f"{sample_id}#e{epoch}", log_arm, NEVER_ATTEMPTED)
                )
    return observations
