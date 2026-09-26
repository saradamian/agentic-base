"""Running retention: the sweep a deployment schedules, and an erasure a person asks for.

`agentic_base.domain.retention` decides which transcripts are due and what erasing one means. This
is the part that touches the database: it reads each tenant's policy, finds the due runs, empties
their personal fields, stamps ``erased_at``, and writes each erasure into the audit log in the
same transaction, so the log shows when and why the content went and still verifies afterwards,
because the log holds digests of what was erased, never the content. A run is exempt from the
sweep only when the service itself stamped it erased; a writer's claim in ``extra`` grants
nothing here.

``agentic-base-retention sweep`` reports what is due and changes nothing unless ``--apply`` is
given. Policies come from ``RETENTION_POLICIES``, a JSON object of tenant to days with ``"*"`` for
every other tenant; a tenant with no policy and no ``"*"`` is skipped and named, never erased by
default, and a policy under the AI Act's six-month floor refuses the whole run.
``agentic-base-retention erase --run-id ... --reason ...`` erases one run's personal fields on request,
whatever its age: the GDPR right to erasure has no minimum period.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from agentic_base.domain import audit
from agentic_base.domain.retention import RetentionPolicy, erase, plan
from agentic_base.domain.run_record import RunRecord, payload_or_none, to_payload

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
    invalid: int = 0
    """Due rows that no longer pass the creation rules; skipped, warned about, not erased."""

    def describe(self, applied: bool) -> str:
        action = (
            f"erased {self.erased}"
            if applied
            else f"would erase {self.due - self.already_erased - self.invalid}"
        )
        described = (
            f"{self.tenant}: examined {self.examined}, due {self.due} (created before "
            f"{self.cutoff.date().isoformat()}), {action}, already erased {self.already_erased}"
        )
        if self.invalid:
            described += (
                f", skipped {self.invalid} that no longer pass the creation rules"
            )
        return described


def _erase_record(
    session: Session, record: RunRecord, now: datetime, reason: str
) -> None:
    erased = erase(to_payload(record), now, reason)
    record.system_prompt = erased.system_prompt
    record.messages = erased.messages
    record.principal = erased.principal
    record.approvals = [approval.model_dump() for approval in erased.approvals]
    record.extra = erased.extra
    record.erased_at = now
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
    """Find a tenant's due transcripts and, when *apply*, erase them in one transaction.

    A due row that no longer passes the creation rules is skipped with a warning and counted
    as ``invalid``, so one such row cannot stop every other transcript in the tenant from
    being erased.
    """
    records = list(
        session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all()
    )
    found = plan(records, now, policy)
    already = 0
    erased = 0
    invalid = 0
    for record in found.due:
        # The exemption is the server's own stamp, never a writer's claim in `extra`.
        if record.erased_at is not None:
            already += 1
        elif payload_or_none(record) is None:
            invalid += 1
        elif apply:
            _erase_record(
                session, record, now, f"{reason}: kept {policy.keep_days} days"
            )
            erased += 1
    if apply:
        session.commit()
    return TenantSweep(
        tenant,
        found.examined,
        found.count,
        erased,
        already,
        found.cutoff,
        invalid=invalid,
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
    """Erase one run's personal fields on request. False when it was already erased."""
    record = session.get(RunRecord, run_id)
    if record is None:
        raise LookupError(f"run not found: {run_id}")
    if record.erased_at is not None:
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
    one = commands.add_parser(
        "erase", help="erase one run's personal fields on request"
    )
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
