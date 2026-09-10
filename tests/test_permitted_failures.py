"""The standing check on permitted failures.

The interesting assertions are the two about not asking, because the whole point of the check is
that silence must not read as a pass.
"""

from __future__ import annotations

import pytest

from scripts.assert_no_permitted_failures import CannotAsk, fetch_jobs, permitted_failures


def _job(name: str, allow_failure: bool = False) -> dict:
    return {"name": name, "allow_failure": allow_failure}


def test_a_pipeline_with_no_permitted_failures_reports_none() -> None:
    jobs = [_job("test"), _job("lint"), _job("build")]

    assert permitted_failures(jobs) == []


def test_a_permitted_failure_is_reported_by_name() -> None:
    jobs = [_job("test"), _job("review:mr", allow_failure=True)]

    assert permitted_failures(jobs) == ["review:mr"]


def test_several_are_reported_in_a_stable_order() -> None:
    jobs = [_job("z", allow_failure=True), _job("a", allow_failure=True), _job("ok")]

    assert permitted_failures(jobs) == ["a", "z"]


def test_an_allowlisted_job_is_tolerated() -> None:
    jobs = [_job("known", allow_failure=True)]

    assert permitted_failures(jobs, allowlist=frozenset({"known"})) == []


def test_the_shipped_allowlist_is_empty() -> None:
    """A check that cannot block should be deleted, not exempted."""
    from scripts.assert_no_permitted_failures import ALLOWLIST

    assert ALLOWLIST == frozenset()


def test_an_unreadable_job_list_raises_instead_of_reporting_clean() -> None:
    """Could not ask is not the same as nothing there, and this is the whole reason for the file."""
    with pytest.raises(CannotAsk):
        fetch_jobs("http://127.0.0.1:1/api/v4", "1", "1", "token")


def test_an_empty_job_list_is_treated_as_a_failure_to_read(monkeypatch) -> None:
    """A real pipeline always has jobs, so an empty answer means the reader is wrong."""
    import scripts.assert_no_permitted_failures as module

    class _Empty:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"[]"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: _Empty())
    monkeypatch.setattr(module.json, "load", lambda f: [])

    with pytest.raises(CannotAsk, match="empty"):
        fetch_jobs("http://example", "1", "1", "t")
