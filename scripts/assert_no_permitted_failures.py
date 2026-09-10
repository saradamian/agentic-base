"""Fail the pipeline if any job in it is permitted to fail.

A job marked `allow_failure` that fails is not a warning, it is silence. The pipeline verdict is
what people read, and a permitted red is indistinguishable from a pass unless someone opens the
job list and then opens the job. That is how two dead gates survived a 165-commit consolidation in
the predecessor project, and how a wrong instruction reached an onboarding document behind a green
pipeline.

Our own pipeline file is asserted statically by `tests/test_process.py`. This is the other half:
most of our jobs come from a shared pipeline component pinned at a version, and that pin is
updated automatically. Reading the component's templates today says something true about today's
version and nothing about the bump that lands next month, at low attention, in an automated merge
request. So the property is asserted against the RUNNING pipeline's own job list, which needs no
visibility into the component and survives every bump.

Failing open would defeat the purpose, so a job list that cannot be read is a failure and not a
pass.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ALLOWLIST: frozenset[str] = frozenset()
"""Jobs permitted to fail, each of which needs a reason in this file.

Empty on purpose. A check that cannot block should be deleted instead of tolerated.
"""

TIMEOUT_S = 30


class CannotAsk(Exception):
    """The job list could not be read. Never treated as an empty answer."""


def fetch_jobs(api_url: str, project_id: str, pipeline_id: str, token: str) -> list[dict]:
    """Every job in the pipeline, following pagination."""
    jobs: list[dict] = []
    page = 1
    while True:
        url = (
            f"{api_url}/projects/{project_id}/pipelines/{pipeline_id}/jobs"
            f"?per_page=100&page={page}&include_retried=true"
        )
        request = urllib.request.Request(url, headers={"JOB-TOKEN": token})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                batch = json.load(response)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise CannotAsk(f"could not read the job list: {exc}") from exc
        if not batch:
            break
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    if not jobs:
        raise CannotAsk("the job list came back empty, which a real pipeline never is")
    return jobs


def permitted_failures(jobs: list[dict], allowlist: frozenset[str] = ALLOWLIST) -> list[str]:
    """Names of jobs that are permitted to fail and are not on the allowlist."""
    return sorted(
        {
            job.get("name", "<unnamed>")
            for job in jobs
            if job.get("allow_failure") and job.get("name") not in allowlist
        }
    )


def main() -> int:
    required = ("CI_API_V4_URL", "CI_PROJECT_ID", "CI_PIPELINE_ID", "CI_JOB_TOKEN")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"cannot ask: missing {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        jobs = fetch_jobs(
            os.environ["CI_API_V4_URL"],
            os.environ["CI_PROJECT_ID"],
            os.environ["CI_PIPELINE_ID"],
            os.environ["CI_JOB_TOKEN"],
        )
    except CannotAsk as exc:
        print(f"cannot ask: {exc}", file=sys.stderr)
        return 1

    offenders = permitted_failures(jobs)
    print(f"examined {len(jobs)} jobs in pipeline {os.environ['CI_PIPELINE_ID']}")
    if offenders:
        print("jobs permitted to fail, which makes their red silent:", file=sys.stderr)
        for name in offenders:
            print(f"  {name}", file=sys.stderr)
        return 1
    print("no job is permitted to fail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
