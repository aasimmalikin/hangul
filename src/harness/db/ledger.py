from decimal import Decimal
from sqlalchemy import select, func
from harness.db.base import SessionLocal
from harness.db.models import Transaction

def get_balance(user_id: str)-> Decimal:
    with SessionLocal() as session:
        total = session.execute(
            select(func.coalesce(func.sum(Transaction.amount),0)).
            where(Transaction.user_id == int(user_id))
        ).scalar_one()
        return Decimal(str(total))

def record_transaction(user_id: str, amount: Decimal, kind: str, thread_id: str | None = None)->Decimal:
    with SessionLocal() as session:
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
        session.commit()
        return new_balance