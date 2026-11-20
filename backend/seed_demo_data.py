"""Add the requested June–October 2026 demonstration transactions once.

Run from the repository root with PYTHONPATH=backend. The script deliberately
requires exactly one local account so demo data cannot land in the wrong user.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app import create_app, db
from app.models import Category, Transaction, User


MONTHS = {
    6: ("June", {"Salary": 30000, "Freelance": 15000, "Business": 10000}, {"Rent": 8000, "Food": 5000, "Shopping": 4000, "Travel": 2000, "Bills": 3000, "Education": 1000, "Entertainment": 1500, "Healthcare": 500}),
    7: ("July", {"Salary": 30000, "Freelance": 10000, "Business": 5000}, {"Rent": 8000, "Food": 5200, "Shopping": 2500, "Travel": 1800, "Bills": 2500, "Education": 1000, "Entertainment": 1200, "Healthcare": 800}),
    8: ("August", {"Salary": 30000, "Freelance": 12000, "Business": 5000}, {"Rent": 8000, "Food": 5500, "Shopping": 3000, "Travel": 2200, "Bills": 2800, "Education": 1500, "Entertainment": 1000, "Healthcare": 1000}),
    9: ("September", {"Salary": 30000, "Freelance": 8000, "Business": 7000}, {"Rent": 8000, "Food": 4800, "Shopping": 3500, "Travel": 2000, "Bills": 2600, "Education": 1200, "Entertainment": 1500, "Healthcare": 900}),
    10: ("October", {"Salary": 30000, "Freelance": 12000, "Business": 5000}, {"Rent": 8000, "Food": 6000, "Shopping": 4000, "Travel": 2500, "Bills": 3000, "Education": 1500, "Entertainment": 1200, "Healthcare": 800}),
}

EXPECTED = {6: (55000, 25000), 7: (45000, 23000), 8: (47000, 25000), 9: (45000, 24500), 10: (47000, 27000)}


def seed():
    app = create_app()
    with app.app_context():
        users = User.query.order_by(User.id).all()
        if len(users) != 1:
            raise RuntimeError(f"Expected exactly one local account, found {len(users)}. Refusing to choose an account automatically.")
        user = users[0]
        preexisting = Transaction.query.filter_by(user_id=user.id).filter(~Transaction.description.like("Demo data:%")).order_by(Transaction.transaction_date).all()
        if preexisting:
            print(f"Preserved {len(preexisting)} pre-existing account transactions.")
        category_ids = {(c.name, c.type): c.id for c in Category.query.filter((Category.user_id == user.id) | (Category.user_id.is_(None))).all()}
        records = []
        for month, (month_name, income, expenses) in MONTHS.items():
            if sum(income.values()) != EXPECTED[month][0] or sum(expenses.values()) != EXPECTED[month][1]:
                raise RuntimeError(f"The provided breakdown does not match the expected {month_name} totals.")
            for kind, entries, start_day in (("income", income, 1), ("expense", expenses, 2)):
                for offset, (category_name, amount) in enumerate(entries.items()):
                    category_id = category_ids.get((category_name, kind))
                    if category_id is None:
                        raise RuntimeError(f"Missing {kind} category: {category_name}")
                    description = f"Demo data: {category_name} - {month_name} 2026"
                    tx_date = date(2026, month, min(start_day + offset * 3, 28))
                    exists = Transaction.query.filter_by(user_id=user.id, category_id=category_id, type=kind, transaction_date=tx_date, description=description).first()
                    if not exists:
                        records.append(Transaction(user_id=user.id, category_id=category_id, type=kind, amount=Decimal(amount).quantize(Decimal("0.01")), transaction_date=tx_date, description=description))
        db.session.add_all(records)
        db.session.commit()
        print(f"Added {len(records)} demo transactions for account ID {user.id}.")
        for month, (month_name, income, expenses) in MONTHS.items():
            start, end = date(2026, month, 1), date(2026 if month < 12 else 2027, month + 1 if month < 12 else 1, 1)
            actual = dict(db.session.query(Transaction.type, func.sum(Transaction.amount)).filter(Transaction.user_id == user.id, Transaction.transaction_date >= start, Transaction.transaction_date < end).group_by(Transaction.type).all())
            actual_income = float(actual.get("income", 0))
            actual_expenses = float(actual.get("expense", 0))
            print(f"{month_name} 2026 demo totals: income INR {sum(income.values()):,.0f}; expenses INR {sum(expenses.values()):,.0f}. Stored account totals: income INR {actual_income:,.0f}; expenses INR {actual_expenses:,.0f}.")


if __name__ == "__main__":
    seed()
