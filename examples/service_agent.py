"""A service agent, not a benchmark: what the record answers for a team that runs one.

A merge-request review agent works for developers. Nobody is comparing configurations here, so
there is no arm to speak of; the version it ran as goes in `arm` only so a later upgrade can be
compared. What the team needs is the account of each run: who it acted for, what data it saw,
whether the person knew it was an AI, who approved what it did, and which verdicts on it mean
anything.

Start the service first, in another terminal:

    pip install 'surf-agentic-base[service]'
    REDACTION=patterns just run

Then:

    python examples/service_agent.py      # talks to http://localhost:8080
"""

from __future__ import annotations

import json
import os

import httpx

from agentic_base.client import RunRecorder
from agentic_base.domain.outcomes import (
    DataClass,
    IsolationTier,
    LabelSource,
    authority_of,
)

BASE_URL = os.environ.get("AGENTIC_BASE_URL", "http://localhost:8080")
TENANT = "platform-team"
DISCLOSURE = "every review comment begins 'Automated review:'"

REQUESTS = [
    ("mr-101", "urn:example:alice", "Looks fine; one missing test for the retry path."),
    (
        "mr-102",
        "urn:example:bob",
        "The migration drops a column still read by the exporter.",
    ),
    (
        "mr-103",
        "urn:example:alice",
        "Suggest a fix: pin the base image by digest. Push it?",
    ),
]


def main() -> None:
    recorder = RunRecorder(BASE_URL, tenant=TENANT, code_revision="7c1e0d2")
    ids: dict[str, str] = {}

    print("1. Three reviews, each recorded for the person who asked")
    for mr, person, reply in REQUESTS:
        with recorder.run(
            item=mr,
            arm="reviewer-2026.09",
            model="some-model",
            principal=person,
            classification=DataClass.INTERNAL,
            isolation_tier=IsolationTier.VIRTUALISED,
            disclosure=DISCLOSURE,
        ) as run:
            run.messages = [
                {
                    "role": "user",
                    "content": f"Review {mr}. Questions to ops@example.org.",
                },
                {"role": "assistant", "content": f"Automated review: {reply}"},
            ]
        ids[mr] = run.run_id
    print(f"   recorded {len(ids)} runs")

    print()
    print("2. The agent wanted to push to mr-103; a maintainer decided")
    recorder.approve(
        ids["mr-103"],
        action="push a commit to mr-103",
        decision="approved",
        by="urn:example:maintainer-carol",
        at="2026-09-14T10:00:00Z",
    )
    print("   approval recorded")

    print()
    print("3. Verdicts on the reviews, and which of them mean anything")
    recorder.label(ids["mr-101"], resolved=True, label_source=LabelSource.USER_FEEDBACK)
    recorder.label(
        ids["mr-102"],
        resolved=True,
        label_source=LabelSource.MODEL_JUDGE,
        instrument="judge-1",
    )
    recorder.label(ids["mr-103"], resolved=True, label_source=LabelSource.HUMAN)
    for mr, who in (
        ("mr-101", "the developer's thumbs-up"),
        ("mr-102", "another model's score"),
        ("mr-103", "the maintainer's decision"),
    ):
        source = LabelSource(
            httpx.get(f"{BASE_URL}/runs/{ids[mr]}").json()["label_source"]
        )
        print(f"   {mr}  {who:28} {source.value:14} {authority_of(source).value}")

    print()
    print("4. Everything the agent did for alice, from the tenant's export")
    lines = httpx.get(
        f"{BASE_URL}/runs/export", params={"tenant": TENANT}
    ).text.splitlines()
    for line in lines[1:]:
        entry = json.loads(line)
        record = entry["record"]
        if record["principal"] != "urn:example:alice":
            continue
        approvals = ", ".join(
            f"{a['decision']} by {a['by']}" for a in record["approvals"]
        )
        print(f"   {record['item']}: {record['messages'][1]['content']}")
        print(f"     told it was an AI: {record['disclosure']}")
        print(
            f"     data class {record['classification']}, tier {record['isolation_tier']}"
        )
        print(f"     approvals: {approvals or 'none'}")
        print(f"     stored question: {record['messages'][0]['content']}")

    print()
    print("5. Are the records as they were written?")
    integrity = httpx.get(
        f"{BASE_URL}/runs/integrity", params={"tenant": TENANT}
    ).json()
    print(f"   {integrity['summary']}")


if __name__ == "__main__":
    main()
