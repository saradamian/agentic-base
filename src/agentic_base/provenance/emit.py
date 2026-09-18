"""The three emitters. Each imports its library at call time, so the module itself imports
without the ``provenance`` extra and a caller without it gets one sentence naming the extra."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentic_base.domain.outcomes import RunRecordCreate, authority_of

if TYPE_CHECKING:
    from openlineage.client.event_v2 import RunEvent
    from prov.model import ProvDocument
    from rocrate.rocrate import ROCrate

NAMESPACE = "https://github.com/saradamian/agentic-base/ns#"
PRODUCER = "https://github.com/saradamian/agentic-base"
OUTCOME_FACET_SCHEMA = "https://github.com/saradamian/agentic-base/blob/main/docs/schemas/OutcomeRunFacet.json"
PROCESS_RUN_CRATE_PROFILE = "https://w3id.org/ro/wfrun/process/0.5"
EXTRA = "provenance"
RUN_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, PRODUCER)
"""Namespace for deriving an OpenLineage run UUID from a run id that is not one."""


def openlineage_run_id(run_id: str) -> str:
    """The UUID OpenLineage requires for a run, derived when *run_id* is not one.

    PROV and RO-Crate take any string; OpenLineage's ``Run.runId`` must be a UUID and the
    library fails on anything else. A consumer keying runs by an integer or a slug gets one
    stable rule here rather than three private ones, and the original id travels in the facet.
    """
    try:
        return str(uuid.UUID(run_id))
    except ValueError:
        return str(uuid.uuid5(RUN_ID_NAMESPACE, run_id))


def _need(module: str) -> None:
    raise ImportError(
        f"{module} is not installed; provenance emission needs the {EXTRA!r} extra: "
        f"pip install 'surf-agentic-base[{EXTRA}]'"
    )


def _outcome(run: RunRecordCreate) -> dict[str, Any]:
    """The facts every format carries about the outcome and who decided it."""
    return {
        "resolved": run.resolved,
        "label_source": run.label_source.value,
        "authority": authority_of(run.label_source).value,
        "degraded": run.degraded,
        **({"instrument": run.instrument} if run.instrument else {}),
    }


def _stated(facts: dict[str, Any]) -> dict[str, Any]:
    """Only what somebody recorded.

    A field nobody filled arrives as an empty string or a zero, and written into a document it
    stops being an absence and becomes a claim: a run whose energy nobody measured was published
    as having drawn 0.0 joules. `unclassified`, `none` and an empty approvals list stay, because
    each is a statement the record makes on purpose.
    """
    return {k: v for k, v in facts.items() if v != "" and v != 0 and v != {}}


def _environment(run: RunRecordCreate) -> dict[str, Any]:
    return _stated(_environment_fields(run))


def _environment_fields(run: RunRecordCreate) -> dict[str, Any]:
    return {
        "code_revision": run.code_revision,
        "component_versions": dict(run.component_versions),
        "model": run.model,
        "endpoint": run.endpoint,
        "precision": run.precision,
        "principal": run.principal,
        "classification": run.classification.value,
        "isolation_tier": run.isolation_tier.value,
        "redaction": run.redaction,
        "disclosure": run.disclosure,
        "content_marking": run.content_marking,
        "approvals": [a.model_dump() for a in run.approvals],
    }


def _cost(run: RunRecordCreate) -> dict[str, float | int]:
    """Three axes kept apart: tokens price an API, elapsed prices an allocation, joules are
    physical. An axis nobody measured is left out, not reported as zero."""
    return _stated(
        {
            "prompt_tokens": run.prompt_tokens,
            "completion_tokens": run.completion_tokens,
            "elapsed_ms": run.elapsed_ms,
            "joules": run.joules,
        }
    )


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
    doc.add_namespace("run", "urn:surf-agentic-base:run:")
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
            f"ab:{k}": (json.dumps(v) if isinstance(v, dict | list) else v)
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
        sourceRunId: str = ""
        principal: str = ""
        classification: str = "unclassified"
        isolationTier: str = "unspecified"
        redaction: str = "none"
        disclosure: str = "none"
        contentMarking: str = "none"
        approvals: int = 0

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
            instrument=run.instrument,
            arm=run.arm,
            armFingerprint=run.arm_fingerprint,
            status=run.status.value,
            failureKind=run.failure_kind,
            promptTokens=run.prompt_tokens,
            completionTokens=run.completion_tokens,
            elapsedMs=run.elapsed_ms,
            joules=run.joules,
            sourceRunId=run_id,
            principal=run.principal,
            classification=run.classification.value,
            isolationTier=run.isolation_tier.value,
            redaction=run.redaction,
            disclosure=run.disclosure,
            contentMarking=run.content_marking,
            approvals=len(run.approvals),
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
        run=Run(runId=openlineage_run_id(run_id), facets=facets),
        job=Job(namespace=run.tenant, name=run.arm or "(unset)"),
        inputs=inputs,
        outputs=[],
    )


AUTHORING_TOOL = "surf-agentic-base"


def build_process_run_crate(
    run: RunRecordCreate,
    run_id: str,
    created_at: datetime,
    *,
    application: str = "",
) -> ROCrate:
    """The Process Run Crate as a library object, not yet written anywhere.

    Returned unwritten so a consumer can add its own entities, the files a run produced, the
    tool activities inside it, a Slurm job, before serialising, the way :func:`to_prov` and
    :func:`to_openlineage` already hand back a document to extend. The run is a
    ``CreateAction`` whose instrument is the software that ran it and whose result is the
    outcome with its provenance as ``PropertyValue`` entities, which is how the profile says to
    attach facts the vocabulary does not name.

    *application* names the software that performed the run, one of ``component_versions``.
    This library did not: it wrote the crate. Those are two actions and the crate records two,
    the run with the application as its instrument, and the writing of the crate with this
    library as its instrument and the crate as its result, which is how RO-Crate says to record
    the software that produced one. With no application named, every recorded component other
    than this library stands as the instrument; with none recorded at all, the run keeps this
    library there, because the profile requires an instrument and an honest weak answer beats
    a missing one.
    """
    try:
        from rocrate.model import ContextEntity
        from rocrate.rocrate import ROCrate
    except ImportError:
        _need("rocrate")

    crate = ROCrate()
    crate.name = f"agentic run {run_id}"
    crate.root_dataset["conformsTo"] = {"@id": PROCESS_RUN_CRATE_PROFILE}

    versions = run.component_versions

    def software(name: str) -> dict[str, str]:
        properties = {"@type": "SoftwareApplication", "name": name}
        if versions.get(name):
            properties["version"] = versions[name]
        crate.add(ContextEntity(crate, f"#{name}", properties=properties))
        return {"@id": f"#{name}"}

    if application:
        ran = [application]
    else:
        ran = [name for name in versions if name != AUTHORING_TOOL] or [AUTHORING_TOOL]
    instruments = [software(name) for name in ran]
    author = (
        {"@id": f"#{AUTHORING_TOOL}"}
        if AUTHORING_TOOL in ran
        else software(AUTHORING_TOOL)
    )

    def value(name: str, item: Any) -> ContextEntity:
        return crate.add(
            ContextEntity(
                crate,
                f"#{run_id}/{name}",
                properties={
                    "@type": "PropertyValue",
                    "name": name,
                    "value": json.dumps(item)
                    if isinstance(item, dict | list)
                    else str(item),
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
            "instrument": instruments[0] if len(instruments) == 1 else instruments,
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
    crate.root_dataset["mentions"] = {"@id": f"#{run_id}"}
    crate.add(
        ContextEntity(
            crate,
            "#crate-authoring",
            properties={
                "@type": "CreateAction",
                "name": "wrote this crate from the run record",
                "instrument": author,
                "result": {"@id": "./"},
            },
        )
    )
    return crate


def to_process_run_crate(
    run: RunRecordCreate, run_id: str, created_at: datetime, out_dir: Path
) -> Path:
    """:func:`build_process_run_crate`, written to *out_dir*. Returns the metadata file's path."""
    build_process_run_crate(run, run_id, created_at).write(out_dir)
    return Path(out_dir) / "ro-crate-metadata.json"
