"""Emit a run record in the provenance standards, never in a private format.

Three formats, because they answer three different readers: W3C PROV for anyone with a PROV
toolchain, OpenLineage for a lineage backend such as Marquez, and a Process Run Crate for the
research-object world. Each one is produced by that standard's own maintained library, and each
carries the two facts the standards have no field for: which scorer decided the outcome, and
whether that scorer's verdict may be cited. Those travel as declared, documented extensions, one
schema file per format under ``docs/schemas``.
"""

from agentic_base.provenance.emit import (
    OUTCOME_FACET_SCHEMA,
    PROCESS_RUN_CRATE_PROFILE,
    to_openlineage,
    to_process_run_crate,
    to_prov,
)

__all__ = [
    "OUTCOME_FACET_SCHEMA",
    "PROCESS_RUN_CRATE_PROFILE",
    "to_openlineage",
    "to_process_run_crate",
    "to_prov",
]
