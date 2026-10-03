"""The money ledger: one signed row per movement in ``transactions``.

Kinds: ``run_cost`` (-, model spend covered by a paid plan's allowance),
``free_cost`` (-, the same on the free plan, kept apart so the free pool --
what all free users together spent this month -- is one query),
``credit_spend`` (-, spend beyond the allowance, paid from credits) and
``topup`` (+, credits bought). The allowance is not a row: it is the plan's
amount minus the allowance spend since the period started, so it resets by
itself and unused allowance never carries over, while credits never expire.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, func
from harness.db.base import SessionLocal
from harness.db.models import Transaction

ZERO = Decimal("0")
ALLOWANCE_KINDS = ("run_cost", "free_cost")


def _sum(session, user_id: str | None, kinds: tuple[str, ...], since: datetime | None = None) -> Decimal:
    """Sum of ``kinds`` for one user, or across everyone when ``user_id`` is None."""
    q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.kind.in_(kinds))
    if user_id is not None:
        q = q.where(Transaction.user_id == int(user_id))
    if since is not None:
        q = q.where(Transaction.created_at >= since)
    return Decimal(str(session.execute(q).scalar_one()))


def get_balance(user_id: str)-> Decimal:
    with SessionLocal() as session:
        total = session.execute(
            select(func.coalesce(func.sum(Transaction.amount),0)).
            where(Transaction.user_id == int(user_id))
        ).scalar_one()
        return Decimal(str(total))


def record_transaction(user_id: str, amount: Decimal, kind: str, thread_id: str | None = None)->Decimal:
    with SessionLocal() as session:
        new_balance = _add(session, user_id, amount, kind, thread_id)
        session.commit()
        return new_balance


def _add(session, user_id: str, amount: Decimal, kind: str, thread_id: str | None) -> Decimal:
    prior = session.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.user_id == int(user_id))
    ).scalar_one()
    new_balance = Decimal(str(prior)) + amount
    session.add(Transaction(
        user_id = int(user_id),
        amount = amount,
        kind = kind,
        thread_id = thread_id,
        balance_after = new_balance,
    ))
    session.flush()
    return new_balance


def period_usage(user_id: str, since: datetime) -> Decimal:
    """Allowance spent since ``since`` (a positive number)."""
    with SessionLocal() as session:
        return -_sum(session, user_id, ALLOWANCE_KINDS, since)


def free_pool_spent(since: datetime) -> Decimal:
    """What all free users together spent from their allowances since ``since``."""
    with SessionLocal() as session:
        return -_sum(session, None, ("free_cost",), since)


def average_run_cost(since: datetime, min_runs: int = 50) -> Decimal | None:
    """Average cost of one run (all users) since ``since``, or None with fewer
    than ``min_runs`` runs. A run settled across allowance and credits is two
    rows with one thread_id, so rows are summed per thread first."""
    with SessionLocal() as session:
        per_run = (select(func.sum(Transaction.amount).label("total"))
                   .where(Transaction.kind.in_(("run_cost", "free_cost", "credit_spend")),
                          Transaction.created_at >= since, Transaction.thread_id.is_not(None))
                   .group_by(Transaction.thread_id).subquery())
        n, avg = session.execute(select(func.count(), func.avg(per_run.c.total))).one()
    if not n or n < min_runs or avg is None:
        return None
    return -Decimal(avg)


def credit_balance(user_id: str) -> Decimal:
    with SessionLocal() as session:
        return _sum(session, user_id, ("topup", "credit_spend"))


def split_cost(cost: Decimal, allowance_left: Decimal) -> tuple[Decimal, Decimal]:
    """(from allowance, from credits) for a run costing ``cost``."""
    covered = min(cost, max(allowance_left, ZERO))
    return covered, cost - covered


def settle_run(user_id: str, cost: Decimal, *, allowance: Decimal, since: datetime,
               thread_id: str | None = None, allowance_kind: str = "run_cost") -> tuple[Decimal, Decimal]:
    """Charge a finished run: the allowance first, any overflow to credits.
    Credits may go slightly negative -- the pre-run check is what stops the
    next run, so one run can overshoot by at most its own budget."""
    with SessionLocal() as session:
        left = allowance + _sum(session, user_id, ALLOWANCE_KINDS, since)
        covered, overflow = split_cost(cost, left)
        if covered > 0:
            _add(session, user_id, -covered, allowance_kind, thread_id)
        if overflow > 0:
            _add(session, user_id, -overflow, "credit_spend", thread_id)
        session.commit()
        return covered, overflow
