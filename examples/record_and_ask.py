"""Record runs from your own agent into the service, then ask it the questions that matter.

Start the service first, in another terminal, with a token for the example's tenant:

    pip install 'surf-agentic-base[service,provenance]'
    API_TOKENS='{"example-token-0000001": {"tenants": ["example-team"], "label_sources": ["official_harness"]}}' just run

Then:

    python examples/record_and_ask.py              # http://localhost:8080, that token
    AGENTIC_BASE_URL=https://... AGENTIC_BASE_TOKEN=... python examples/record_and_ask.py
"""

from __future__ import annotations

import json
import os

import httpx

from agentic_base.client import RunRecorder
from agentic_base.domain.outcomes import LabelSource, RunStatus

BASE_URL = os.environ.get("AGENTIC_BASE_URL", "http://localhost:8080")
TOKEN = os.environ.get("AGENTIC_BASE_TOKEN", "example-token-0000001")
api = httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {TOKEN}"})
TENANT = "example-team"


def my_agent(task: str) -> list[dict[str, str]]:
    """Stands in for your agent. Task 4 crashes, which is a result too."""
    if task == "task-4":
        raise RuntimeError("the agent's tool call failed")
    return [
        {
            "role": "user",
            "content": f"Fix {task}. Mail the report to jan.devries@example.org.",
        },
        {"role": "assistant", "content": "Done, the tests pass."},
    ]


def main() -> None:
    recorder = RunRecorder(
        BASE_URL, tenant=TENANT, code_revision="3f2a9c1", token=TOKEN
    )
    ids: dict[tuple[str, str], str] = {}

    print(f"1. Recording 12 runs to {BASE_URL}")
    for arm in ("baseline", "with-planner"):
        for n in range(1, 7):
            task = f"task-{n}"
            try:
                with recorder.run(item=task, arm=arm, model="some-model") as run:
                    if arm == "with-planner" and n >= 5:
                        run.status = RunStatus.TIMEOUT
                        continue
                    run.messages = my_agent(task)
            except RuntimeError:
                pass  # recorded as failed on the way out, with the exception's name
            ids[(arm, task)] = run.run_id

    stored = api.get(f"/runs/{ids[('baseline', 'task-4')]}").json()
    print(
        f"   the run that crashed was kept: status={stored['status']}, failure_kind={stored['failure_kind']}"
    )

    print()
    print("2. Labelling the finished runs with the benchmark's own harness")
    for (arm, task), run_id in ids.items():
        if (arm, task) in {("with-planner", "task-5"), ("with-planner", "task-6")}:
            continue
        recorder.label(
            run_id,
            resolved=task in {"task-1", "task-2", "task-3"},
            label_source=LabelSource.OFFICIAL_HARNESS,
            instrument="harness-1.4",
        )
    refused = api.post(
        f"/runs/{ids[('baseline', 'task-1')]}/label", json={"resolved": True}
    )
    print(f"   a label that names no scorer is refused: HTTP {refused.status_code}")

    print()
    print("3. Is the comparison sound?")
    report = api.get("/runs/validity/report", params={"tenant": TENANT}).json()
    print(f"   {report['summary']}")
    for arm in report["flow"]:
        print(f"   {arm['description']}")

    print()
    print("4. Are the records as they were written?")
    integrity = api.get("/runs/integrity", params={"tenant": TENANT}).json()
    print(f"   {integrity['summary']}")

    print()
    print("5. What was stored of the transcript")
    print(
        f"   {stored['messages'][0]['content'] if stored['messages'] else '(the crashed run has no transcript)'}"
    )
    first = api.get(f"/runs/{ids[('baseline', 'task-1')]}").json()
    print(f"   {first['messages'][0]['content']}")
    print(f"   redaction: {first['redaction']}")

    print()
    print("6. One run in W3C PROV, for a reader that is not this service")
    prov = api.get(
        f"/runs/{ids[('baseline', 'task-1')]}/provenance",
        params={"format": "prov"},
    ).json()
    print(f"   sections: {', '.join(sorted(prov))}")
    outcome = next(v for k, v in prov["entity"].items() if k.endswith("/outcome"))
    print(f"   the outcome: {json.dumps(outcome, sort_keys=True)}")

    print()
    print("7. Everything this tenant recorded, to take elsewhere")
    lines = api.get("/runs/export", params={"tenant": TENANT}).text.splitlines()
    manifest = json.loads(lines[0])
    print(
        f"   manifest says {manifest['records']} records; the file has {len(lines) - 1}"
    )
    anonymous = httpx.get(f"{BASE_URL}/runs/export", params={"tenant": TENANT})
    print(f"   the same request without the token: HTTP {anonymous.status_code}")


if __name__ == "__main__":
    main()
