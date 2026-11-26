"""capacity_reservations: the capacity that each open request holds on its cluster (#62; docs/02, Placement, "Reservations").

The columns are docs/02's, with three added:

- `namespace`: the namespace whose quota the request changes. docs/02 reaches it through `request_id`; the capacity check reads
  it for every active hold, so it is kept on the row instead of a join on each plan.
- `target_cpu` and `target_memory`: the namespace's binding quota after the change. docs/02: "The reservation ends when the
  namespace's ResourceQuota appears in cmapi's watch cache of that cluster. Committed quota counts it from then on, so it is
  never counted twice." The check compares them with the cluster's quota ledger and stops counting a hold that the ledger
  already shows (core/capacity_backend.py).

A placement hold (POST /api/v1/capacity:place, not built) has no request and no namespace yet, so both stay nullable.

The upgrade also holds the increases of the requests already in flight, which 0010's code recorded without one: each in a
state that holds a reservation (docs/01's Reservation column) holds the increase of its stored plan from the upgrade on, for
one term, as a step of the lifecycle would. A failed one keeps its amounts released, for its :retry to take again and check
(docs/01: ":retry re-acquires lock and reservation"). An empty table would let them overbook until each one ended (#725
review). The amounts are the planner's: the binding quota of the plan's files over that of the files before, for a create
over none (core/pipeline.py), rounded as SimulatedCapacity.reserve rounds them. The downgrade drops the holds with the table;
an upgrade after it fills them again from the requests' states then.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-26
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import sqlalchemy as sa
import yaml
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capacity_reservations",
        sa.Column("reservation_id", sa.Uuid, primary_key=True),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("change_requests.request_id")),
        sa.Column("cluster_id", sa.String(63), nullable=False),
        sa.Column("namespace", sa.String(63)),
        sa.Column("zone", sa.String(63)),
        sa.Column("cpu", sa.Numeric(12, 3), nullable=False),
        sa.Column("memory", sa.BigInteger, nullable=False),
        sa.Column("pods", sa.Integer, nullable=False),
        sa.Column("target_cpu", sa.Numeric(12, 3)),
        sa.Column("target_memory", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("released_why", sa.String(20)),
        sa.CheckConstraint("cpu >= 0 AND memory >= 0 AND pods >= 0", name="ck_resv_amounts"),
        sa.CheckConstraint("(released_at IS NULL) = (released_why IS NULL)", name="ck_resv_released"),
    )
    # The check sums a cluster's active holds on every plan; a request's own hold is found by its id.
    op.create_index("idx_resv_active", "capacity_reservations", ["cluster_id"], postgresql_where=sa.text("released_at IS NULL"))
    op.create_index("idx_resv_request", "capacity_reservations", ["request_id"])
    _hold_requests_in_flight()


# The states that hold a reservation at this revision (core/lifecycle.py, _RESERVATION), and failed, whose :retry takes the
# request's last amounts again (RequestRepo.reacquire).
HOLDING = ("pending_approval", "approved", "pr_open", "applied", "merge_failed", "merged")
RESOURCES = {"cpu": "requests.cpu", "memory": "requests.memory", "pods": "pods"}
log = logging.getLogger("alembic.runtime.migration")


def _hold_requests_in_flight() -> None:
    from cmapi.core.capacity_ledger import binding_hard
    from cmapi.core.render.manifests import objects_of, own_quota
    from cmapi.core.tiers import qty

    bind = op.get_bind()
    # No request moves between the read below and the commit: one that 0010's code ended meanwhile would hold for a term.
    op.execute("LOCK TABLE change_requests IN SHARE MODE")
    now = bind.execute(sa.text("SELECT now()")).scalar_one()
    holds = sa.table("capacity_reservations", *(sa.column(c) for c in (
        "reservation_id", "request_id", "cluster_id", "namespace", "cpu", "memory", "pods", "target_cpu", "target_memory",
        "created_at", "expires_at", "released_at", "released_why")))
    rows = bind.execute(sa.text(
        "SELECT request_id, cluster_id, namespace, action, status, plan, requirement FROM change_requests "
        "WHERE action IN ('create', 'update') AND status IN :states ORDER BY request_id"
    ).bindparams(sa.bindparam("states", expanding=True)), {"states": [*HOLDING, "failed"]}).mappings().all()

    def hard(files, namespace: str) -> dict[str, str]:
        quota = own_quota(objects_of(files or {}, "ResourceQuota"), namespace)
        return binding_hard(((quota or {}).get("spec") or {}).get("hard"))

    for row in rows:
        plan = row["plan"] or {}
        try:
            ns = row["namespace"]
            new, old = hard(plan.get("files"), ns), hard(plan.get("prev"), ns) if row["action"] != "create" else {}
            delta = {k: qty(new.get(key, "0")) - qty(old.get(key, "0")) for k, key in RESOURCES.items()}
            target = {k: qty(new[RESOURCES[k]]) if RESOURCES[k] in new else None for k in ("cpu", "memory")}
        except (ValueError, yaml.YAMLError) as exc:
            log.warning("0011: %s holds nothing, its stored plan cannot be read: %s", row["request_id"], exc)
            continue
        cpu, memory = max(delta["cpu"], Decimal(0)), max(delta["memory"], Decimal(0))
        if cpu <= 0 and memory <= 0:
            continue                                     # a decrease or a label change holds nothing
        failed = row["status"] == "failed"
        bind.execute(holds.insert().values(
            reservation_id=uuid.uuid4(), request_id=row["request_id"], cluster_id=row["cluster_id"],
            namespace=row["namespace"], cpu=_round(cpu, 3, ROUND_CEILING), memory=int(_round(memory, 0, ROUND_CEILING)),
            pods=max(int(delta["pods"]), 0),
            target_cpu=None if target["cpu"] is None else _round(target["cpu"], 3, ROUND_FLOOR),
            target_memory=None if target["memory"] is None else int(_round(target["memory"], 0, ROUND_FLOOR)),
            created_at=now, expires_at=now + timedelta(hours=(row["requirement"] or {}).get("timeoutHours", 24) + 1),
            released_at=now if failed else None, released_why="failed" if failed else None))


def _round(value: Decimal, places: int, rounding: str) -> Decimal:
    """As SimulatedCapacity.reserve stores a hold: its amounts up, never smaller than what was checked; its targets down,
    so that the live quota reaches them."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=rounding)


def downgrade() -> None:
    # Holds are live state of open requests: dropping the table lets them overbook until each one ends.
    op.drop_table("capacity_reservations")
