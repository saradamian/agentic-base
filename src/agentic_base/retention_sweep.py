"""Running retention: the sweep a deployment schedules, and an erasure a person asks for.

`agentic_base.domain.retention` decides which transcripts are due and what erasing one means. This
is the part that touches the database: it reads each tenant's policy, finds the due runs, empties
their transcripts, and writes each erasure into the audit log in the same transaction, so the log
shows when and why a transcript went and still verifies afterwards, because nothing the log covers
changed.

``agentic-base-retention sweep`` reports what is due and changes nothing unless ``--apply`` is
given. Policies come from ``RETENTION_POLICIES``, a JSON object of tenant to days with ``"*"`` for
every other tenant; a tenant with no policy and no ``"*"`` is skipped and named, never erased by
default, and a policy under the AI Act's six-month floor refuses the whole run.
``agentic-base-retention erase --run-id ... --reason ...`` erases one run's transcript on request,
whatever its age: the GDPR right to erasure has no minimum period.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from agentic_base.domain import audit
from agentic_base.domain.retention import RetentionPolicy, erase, plan, was_erased
from agentic_base.domain.run_record import RunRecord, to_payload

ALL_TENANTS = "*"


def parse_policies(raw: str) -> dict[str, RetentionPolicy]:
    """``{"tenant": days, "*": days}`` into policies. Refuses anything malformed or under the floor."""
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"RETENTION_POLICIES is not valid JSON: {exc.msg}") from None
    if not isinstance(loaded, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
        for k, v in loaded.items()
    ):
        raise ValueError(
            "RETENTION_POLICIES must be a JSON object of tenant name to whole days"
        )
    return {tenant: RetentionPolicy(keep_days=days) for tenant, days in loaded.items()}


@dataclass(frozen=True)
class TenantSweep:
    tenant: str
    examined: int
    due: int
    erased: int
    already_erased: int
    cutoff: datetime

    def describe(self, applied: bool) -> str:
        action = (
            f"erased {self.erased}"
            if applied
            else f"would erase {self.due - self.already_erased}"
        )
        return (
            f"{self.tenant}: examined {self.examined}, due {self.due} (created before "
            f"{self.cutoff.date().isoformat()}), {action}, already erased {self.already_erased}"
        )


def _erase_record(
    session: Session, record: RunRecord, now: datetime, reason: str
) -> None:
    erased = erase(to_payload(record), now, reason)
    record.system_prompt = erased.system_prompt
    record.messages = erased.messages
    record.extra = erased.extra
    session.add(record)
    audit.append(session, record, "erased")


def sweep_tenant(
    session: Session,
    tenant: str,
    policy: RetentionPolicy,
    now: datetime,
    *,
    apply: bool,
    reason: str = "retention policy",
) -> TenantSweep:
    """Find a tenant's due transcripts and, when *apply*, erase them in one transaction."""
    records = list(
        session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all()
    )
    found = plan(records, now, policy)
    already = sum(1 for r in found.due if was_erased(to_payload(r)))
    erased = 0
    if apply:
        for record in found.due:
            if not was_erased(to_payload(record)):
                _erase_record(
                    session, record, now, f"{reason}: kept {policy.keep_days} days"
                )
                erased += 1
        session.commit()
    return TenantSweep(
        tenant, found.examined, found.count, erased, already, found.cutoff
    )


def sweep(
    session: Session,
    policies: dict[str, RetentionPolicy],
    now: datetime,
    *,
    apply: bool,
) -> tuple[list[TenantSweep], list[str]]:
    """Every tenant with runs: swept under its policy, or listed as skipped when it has none."""
    tenants = sorted(set(session.exec(select(RunRecord.tenant)).all()))
    done: list[TenantSweep] = []
    skipped: list[str] = []
    for tenant in tenants:
        policy = policies.get(tenant) or policies.get(ALL_TENANTS)
        if policy is None:
            skipped.append(tenant)
            continue
        done.append(sweep_tenant(session, tenant, policy, now, apply=apply))
    return done, skipped


def erase_run(session: Session, run_id: str, reason: str, now: datetime) -> bool:
    """Erase one run's transcript on request. False when it was already erased."""
    record = session.get(RunRecord, run_id)
    if record is None:
        raise LookupError(f"run not found: {run_id}")
    if was_erased(to_payload(record)):
        return False
    _erase_record(session, record, now, reason)
    session.commit()
    return True


def main(argv: list[str] | None = None) -> int:
    """The ``agentic-base-retention`` command."""
    parser = argparse.ArgumentParser(
        prog="agentic-base-retention", description=__doc__.split("\n\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "sweep", help="erase transcripts older than each tenant's policy"
    )
    run.add_argument(
        "--apply", action="store_true", help="erase; without it, only report"
    )
    one = commands.add_parser("erase", help="erase one run's transcript on request")
    one.add_argument("--run-id", required=True)
    one.add_argument("--reason", required=True)
    args = parser.parse_args(argv)

    from agentic_base.config import get_settings
    from agentic_base.db import get_engine, init_db

    init_db()
    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        if args.command == "erase":
            erased = erase_run(session, args.run_id, args.reason, now)
            print(f"run {args.run_id}: {'erased' if erased else 'already erased'}")
            return 0
        policies = parse_policies(get_settings().retention_policies)
        if not policies:
            print("no RETENTION_POLICIES configured; nothing swept")
            return 1
        done, skipped = sweep(session, policies, now, apply=args.apply)
    for result in done:
        print(result.describe(args.apply))
    if skipped:
        print(f"no policy, not swept: {', '.join(skipped)}")
    if not args.apply:
        print("dry run: nothing erased; add --apply to erase")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
