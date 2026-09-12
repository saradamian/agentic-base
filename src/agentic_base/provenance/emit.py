"""The three emitters. Each imports its library at call time, so the module itself imports
without the ``provenance`` extra and a caller without it gets one sentence naming the extra."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentic_base.domain.outcomes import RunRecordCreate, authority_of

if TYPE_CHECKING:
    from openlineage.client.event_v2 import RunEvent
    from prov.model import ProvDocument

NAMESPACE = "https://github.com/saradamian/agentic-base/ns#"
PRODUCER = "https://github.com/saradamian/agentic-base"
OUTCOME_FACET_SCHEMA = "https://github.com/saradamian/agentic-base/blob/main/docs/schemas/OutcomeRunFacet.json"
PROCESS_RUN_CRATE_PROFILE = "https://w3id.org/ro/wfrun/process/0.5"
EXTRA = "provenance"


def _need(module: str) -> None:
    raise ImportError(
        f"{module} is not installed; provenance emission needs the {EXTRA!r} extra: "
        f"pip install 'agentic-base[{EXTRA}]'"
    )


def _outcome(run: RunRecordCreate) -> dict[str, Any]:
    """The facts every format carries about the outcome and who decided it."""
    return {
        "resolved": run.resolved,
        "label_source": run.label_source.value,
        "authority": authority_of(run.label_source).value,
        "degraded": run.degraded,
        "instrument": run.instrument,
    }


def _environment(run: RunRecordCreate) -> dict[str, Any]:
    return {
        "code_revision": run.code_revision,
        "component_versions": dict(run.component_versions),
        "model": run.model,
        "endpoint": run.endpoint,
        "precision": run.precision,
    }


def _cost(run: RunRecordCreate) -> dict[str, float | int]:
    """Three axes kept apart: tokens price an API, elapsed prices an allocation, joules are
    physical."""
    return {
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "elapsed_ms": run.elapsed_ms,
        "joules": run.joules,
    }


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")


def to_prov(run: RunRecordCreate, run_id: str, created_at: datetime) -> ProvDocument:
    """W3C PROV. The run is an activity, the environment an entity it used, the outcome an
    entity it generated, and the scorer an agent the outcome is attributed to."""
    try:
        from prov.model import ProvDocument
    except ImportError:
        _need("prov")

    doc = ProvDocument()
    doc.add_namespace("ab", NAMESPACE)
    doc.add_namespace("run", "urn:agentic-base:run:")
    activity = doc.activity(
        f"run:{run_id}",
        startTime=created_at,
        other_attributes={
            "ab:tenant": run.tenant,
            "ab:item": run.item,
            "ab:arm": run.arm,
            "ab:arm_fingerprint": run.arm_fingerprint,
            "ab:status": run.status.value,
            "ab:failure_kind": run.failure_kind,
            **{f"ab:{k}": v for k, v in _cost(run).items()},
        },
    )
    environment = doc.entity(
        f"run:{run_id}/environment",
        {
            f"ab:{k}": (json.dumps(v) if isinstance(v, dict) else v)
            for k, v in _environment(run).items()
        },
    )
    doc.used(activity, environment)
    if run.resolved is not None:
        outcome = doc.entity(
            f"run:{run_id}/outcome", {f"ab:{k}": v for k, v in _outcome(run).items()}
        )
        scorer = doc.agent(
            f"ab:scorer/{run.label_source.value}",
            {"ab:authority": authority_of(run.label_source).value},
        )
        doc.wasGeneratedBy(outcome, activity)
        doc.wasAttributedTo(outcome, scorer)
        doc.wasAssociatedWith(activity, scorer)
    return doc


def to_openlineage(run: RunRecordCreate, run_id: str, created_at: datetime) -> RunEvent:
    """An OpenLineage run event. The job is the arm within the tenant; the outcome and its
    authority ride in a declared run facet whose schema is ``OUTCOME_FACET_SCHEMA``."""
    try:
        import attr
        from openlineage.client.event_v2 import (
            InputDataset,
            Job,
            Run,
            RunEvent,
            RunState,
        )
        from openlineage.client.facet_v2 import RunFacet, processing_engine_run
    except ImportError:
        _need("openlineage-python")

    @attr.define
    class OutcomeRunFacet(RunFacet):  # type: ignore[misc]
        resolved: bool | None = None
        labelSource: str = ""
        authority: str = ""
        degraded: bool = False
        instrument: str = ""
        arm: str = ""
        armFingerprint: str = ""
        status: str = ""
        failureKind: str = ""
        promptTokens: int = 0
        completionTokens: int = 0
        elapsedMs: float = 0.0
        joules: float = 0.0

        @staticmethod
        def _get_schema() -> str:
            return OUTCOME_FACET_SCHEMA

    outcome = _outcome(run)
    facets: dict[str, Any] = {
        "agenticBaseOutcome": OutcomeRunFacet(
            resolved=outcome["resolved"],
            labelSource=outcome["label_source"],
            authority=outcome["authority"],
            degraded=outcome["degraded"],
            instrument=outcome["instrument"],
            arm=run.arm,
            armFingerprint=run.arm_fingerprint,
            status=run.status.value,
            failureKind=run.failure_kind,
            promptTokens=run.prompt_tokens,
            completionTokens=run.completion_tokens,
            elapsedMs=run.elapsed_ms,
            joules=run.joules,
        ),
    }
    versions = run.component_versions
    if versions:
        name, version = sorted(versions.items())[0]
        facets["processing_engine"] = processing_engine_run.ProcessingEngineRunFacet(
            version=version, name=name
        )
    state = RunState.COMPLETE if run.status.value == "completed" else RunState.FAIL
    inputs = (
        [InputDataset(namespace="code", name=run.code_revision)]
        if run.code_revision
        else []
    )
    return RunEvent(
        eventTime=_iso(created_at),
        producer=PRODUCER,
        eventType=state,
        run=Run(runId=run_id, facets=facets),
        job=Job(namespace=run.tenant, name=run.arm or "(unset)"),
        inputs=inputs,
        outputs=[],
    )


def to_process_run_crate(
    run: RunRecordCreate, run_id: str, created_at: datetime, out_dir: Path
) -> Path:
    """A Process Run Crate written to *out_dir*. Returns the metadata file's path.

    The run is a ``CreateAction`` whose instrument is the software that ran it and whose result
    is the outcome with its provenance as ``PropertyValue`` entities, which is how the profile
    says to attach facts the vocabulary does not name.
    """
    try:
        from rocrate.model import ContextEntity
        from rocrate.rocrate import ROCrate
    except ImportError:
        _need("rocrate")

    crate = ROCrate()
    crate.name = f"agentic run {run_id}"
    crate.root_dataset["conformsTo"] = {"@id": PROCESS_RUN_CRATE_PROFILE}

    software_id = "#agentic-base"
    versions = run.component_versions
    crate.add(
        ContextEntity(
            crate,
            software_id,
            properties={
                "@type": "SoftwareApplication",
                "name": "agentic-base",
                "version": versions.get("agentic-base", ""),
            },
        )
    )

    def value(name: str, item: Any) -> ContextEntity:
        return crate.add(
            ContextEntity(
                crate,
                f"#{run_id}/{name}",
                properties={
                    "@type": "PropertyValue",
                    "name": name,
                    "value": json.dumps(item) if isinstance(item, dict) else str(item),
                },
            )
        )

    results = (
        [value(k, v) for k, v in _outcome(run).items()]
        if run.resolved is not None
        else []
    )
    objects = [value(k, v) for k, v in {**_environment(run), **_cost(run)}.items()]
    action = ContextEntity(
        crate,
        f"#{run_id}",
        properties={
            "@type": "CreateAction",
            "name": f"run {run_id}",
            "startTime": _iso(created_at),
            "instrument": {"@id": software_id},
            "actionStatus": {
                "@id": "http://schema.org/CompletedActionStatus"
                if run.status.value == "completed"
                else "http://schema.org/FailedActionStatus"
            },
            "description": json.dumps(
                {
                    "tenant": run.tenant,
                    "item": run.item,
                    "arm": run.arm,
                    "arm_fingerprint": run.arm_fingerprint,
                }
            ),
        },
    )
    crate.add(action)
    action["object"] = objects
    if results:
        action["result"] = results
    crate.write(out_dir)
    return Path(out_dir) / "ro-crate-metadata.json"
