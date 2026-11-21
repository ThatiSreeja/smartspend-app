import csv
import smtplib
import io
import json
import os
import re
import urllib.error
import urllib.request
from hmac import compare_digest
from email.message import EmailMessage
from calendar import month_abbr, month_name, monthrange
from datetime import date, timedelta
from time import time
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request, Response
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app import db, limiter
from app.models import AIInsight, Budget, Category, RevokedAccessToken, Transaction, User
from app.financial_assistant import (
    FinancialAnalytics, INTENTS, NO_RECORDS, answer_financial, intent_for, read_date_range, read_periods, shift,
)

api = Blueprint("api", __name__, url_prefix="/api")
INCOME = ["Salary", "Freelance", "Business", "Investments", "Other Income"]
EXPENSE = ["Food", "Shopping", "Travel", "Rent", "Bills", "Healthcare", "Education", "Entertainment", "Other Expenses"]
VALID_EMAIL = re.compile(r"[^\s@]+@[^\s@]+")


def error(message, status=400):
    return jsonify({"error": message}), status


@api.before_request
def validate_json_body():
    if request.method in {"POST", "PUT"} and not isinstance(request.get_json(silent=True), dict):
        return error("Send a JSON object.")


def account_token(user):
    return create_access_token(identity=str(user.id), additional_claims={
        "pv": user.password_marker(current_app.config["JWT_SECRET_KEY"]),
    })


def password_reset_token(user):
    secret = current_app.config["SECRET_KEY"]
    return URLSafeTimedSerializer(secret).dumps(
        {"id": user.id, "version": user.password_marker(secret)}, salt="smartspend-password-reset",
    )


def current_user():
    return db.session.get(User, int(get_jwt_identity()))


def owned_category(category_id, user_id, kind=None):
    if not 1 <= category_id <= 2147483647:
        return None
    category = db.session.get(Category, category_id)
    if not category or category.user_id not in (None, user_id) or (kind and category.type != kind):
        return None
    return category


def period_args():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        if not 1900 <= year <= 9998:
            raise ValueError
        month = request.args.get("month", str(today.month))
        if month == "all":
            return date(year, 1, 1), date(year + 1, 1, 1), year, None
        month = int(month)
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        return start, end, year, month
    except (ValueError, TypeError):
        raise ValueError("Use a valid year and month (1–12 or all).")


@api.post("/auth/register")
@limiter.limit("5 per hour")
def register():
    data = request.get_json(silent=True) or {}
    name, email, password = str(data.get("name", "")).strip(), str(data.get("email", "")).strip().lower(), data.get("password", "")
    if not 2 <= len(name) <= 120 or len(email) > 254 or not VALID_EMAIL.fullmatch(email):
        return error("Enter a valid name and email.")
    if not isinstance(password, str) or not 8 <= len(password) <= 1024:
        return error("Password must contain 8 to 1024 characters.")
    if User.query.filter_by(email=email).first():
        return error("An account with this email already exists.", 409)
    user = User(name=name, email=email, currency="INR")
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.flush()
        if not Category.query.filter(Category.user_id.is_(None)).first():
            db.session.add_all([Category(user_id=user.id, name=n, type="income") for n in INCOME] + [Category(user_id=user.id, name=n, type="expense") for n in EXPENSE])
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if User.query.filter_by(email=email).first():
            return error("An account with this email already exists.", 409)
        raise
    return jsonify({"user": user.public(), "access_token": account_token(user)}), 201


@api.post("/auth/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=str(data.get("email", "")).strip().lower()).first()
    if not user or not user.check_password(data.get("password", "")):
        return error("Email or password is incorrect.", 401)
    return jsonify({"user": user.public(), "access_token": account_token(user)})


@api.post("/auth/logout")
@jwt_required(skip_revocation_check=True)
def logout():
    token = get_jwt()
    if db.session.get(RevokedAccessToken, token["jti"]) is None:
        db.session.execute(db.delete(RevokedAccessToken).where(RevokedAccessToken.expires_at <= int(time())))
        db.session.add(RevokedAccessToken(jti=token["jti"], expires_at=token["exp"]))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if db.session.get(RevokedAccessToken, token["jti"]) is None:
                raise
    return "", 204


@api.post("/auth/forgot-password")
@limiter.limit("4 per hour")
def forgot_password():
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()
    user = User.query.filter_by(email=email).first() if email else None
    # Respond identically whether the account exists or mail is configured.
    if user and current_app.config.get("SMTP_HOST") and current_app.config.get("SMTP_USER"):
        token = password_reset_token(user)
        link = f"{current_app.config.get('CORS_ORIGINS', ['http://localhost:5173'])[0]}/reset-password?token={token}"
        message = EmailMessage()
        message["Subject"] = "Reset your SmartSpend password"
        message["From"] = current_app.config.get("SMTP_FROM") or current_app.config["SMTP_USER"]
        message["To"] = user.email
        message.set_content(f"Use this link within 30 minutes to reset your password:\n\n{link}\n\nIf you did not request this, ignore this email.")
        try:
            with smtplib.SMTP(current_app.config["SMTP_HOST"], int(current_app.config.get("SMTP_PORT", 587)), timeout=10) as server:
                server.starttls()
                server.login(current_app.config["SMTP_USER"], current_app.config["SMTP_PASSWORD"])
                server.send_message(message)
        except (OSError, smtplib.SMTPException):
            current_app.logger.warning("Password reset email could not be sent")
    return jsonify({"message": "If an account exists and email delivery is configured, a reset link will be sent."})


@api.post("/auth/reset-password")
@limiter.limit("5 per hour")
def reset_password():
    data = request.get_json(silent=True) or {}
    token, password = data.get("token", ""), data.get("password", "")
    if not isinstance(password, str) or not 8 <= len(password) <= 1024:
        return error("Password must contain 8 to 1024 characters.")
    invalid = "This reset link is invalid or expired. Request a new one."
    if not isinstance(token, str):
        return error(invalid)
    secret = current_app.config["SECRET_KEY"]
    try:
        payload = URLSafeTimedSerializer(secret).loads(token, salt="smartspend-password-reset", max_age=1800)
    except (BadSignature, SignatureExpired):
        return error(invalid)
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int) or not isinstance(payload.get("version"), str):
        return error(invalid)
    user = db.session.get(User, payload["id"])
    if not user or not compare_digest(payload["version"], user.password_marker(secret)):
        return error(invalid)
    replacement = User()
    replacement.set_password(password)
    changed = User.query.filter_by(id=user.id, password_hash=user.password_hash).update(
        {User.password_hash: replacement.password_hash, User.updated_at: func.now()}, synchronize_session=False,
    )
    if not changed:
        db.session.rollback()
        return error(invalid)
    db.session.commit()
    return jsonify({"message": "Password reset. You can now sign in."})


@api.get("/auth/me")
@jwt_required()
def me():
    return jsonify({"user": current_user().public()})


@api.put("/profile")
@jwt_required()
def profile():
    user, data = current_user(), request.get_json(silent=True) or {}
    name = str(data.get("name", user.name)).strip()
    email = str(data.get("email", user.email)).strip().lower()
    currency = str(data.get("currency", user.currency)).upper()
    if not 2 <= len(name) <= 120 or len(email) > 254 or not VALID_EMAIL.fullmatch(email) or not re.fullmatch(r"[A-Z]{3}", currency):
        return error("Enter a valid name, email, and 3-letter currency code.")
    if User.query.filter(User.email == email, User.id != user.id).first():
        return error("That email is already in use.", 409)
    user.name, user.email, user.currency = name, email, currency
    db.session.commit()
    return jsonify({"user": user.public()})


@api.put("/profile/password")
@jwt_required()
def change_password():
    data, user = request.get_json(silent=True) or {}, current_user()
    if not user.check_password(data.get("current_password", "")):
        return error("Current password is incorrect.", 401)
    new = data.get("new_password", "")
    if not isinstance(new, str) or not 8 <= len(new) <= 1024:
        return error("New password must contain 8 to 1024 characters.")
    user.set_password(new)
    db.session.commit()
    return jsonify({"message": "Password updated."})


@api.get("/categories")
@jwt_required()
def categories():
    uid = int(get_jwt_identity())
    return jsonify([c.public() for c in Category.query.filter((Category.user_id == uid) | (Category.user_id.is_(None))).order_by(Category.type, Category.name).all()])


@api.post("/categories")
@jwt_required()
def create_category():
    uid, data = int(get_jwt_identity()), request.get_json(silent=True) or {}
    name, kind = str(data.get("name", "")).strip(), data.get("type")
    if not name or len(name) > 80 or kind not in ("income", "expense"):
        return error("Provide a category name and type (income or expense).")
    if Category.query.filter_by(user_id=uid, name=name, type=kind).first():
        return error("That category already exists.", 409)
    category = Category(user_id=uid, name=name, type=kind)
    db.session.add(category); db.session.commit()
    return jsonify(category.public()), 201


@api.delete("/categories/<int:category_id>")
@jwt_required()
def delete_category(category_id):
    uid = int(get_jwt_identity())
    category = Category.query.filter_by(id=category_id, user_id=uid).first()
    if not category:
        return error("Category not found.", 404)
    if Transaction.query.filter_by(category_id=category.id).first() or Budget.query.filter_by(category_id=category.id).first():
        return error("This category has transactions or budgets and cannot be deleted.", 409)
    db.session.delete(category); db.session.commit()
    return jsonify({"message": "Category deleted."})


def transaction_values(data, uid, existing=None):
    kind = data.get("type", existing.type if existing else None)
    try:
        amount = Decimal(str(data.get("amount", existing.amount if existing else "")))
        when = date.fromisoformat(data.get("transaction_date", existing.transaction_date.isoformat() if existing else ""))
        category_id = int(data.get("category_id", existing.category_id if existing else 0))
    except (ValueError, InvalidOperation, TypeError):
        return None, "Amount, category, and date must be valid."
    if not amount.is_finite() or not Decimal("0.01") <= amount <= Decimal("9999999999.99") or kind not in ("income", "expense"):
        return None, "Enter a positive amount and valid transaction type."
    category = owned_category(category_id, uid, kind)
    if not category:
        return None, "Choose a category belonging to your account and matching the transaction type."
    description = str(data.get("description", existing.description if existing else "")).strip()
    if len(description) > 500:
        return None, "Description must be 500 characters or fewer."
    return {"amount": amount.quantize(Decimal("0.01")), "type": kind, "category": category, "date": when, "description": description}, None


@api.get("/transactions")
@jwt_required()
def list_transactions():
    uid = int(get_jwt_identity())
    query = Transaction.query.filter_by(user_id=uid)
    search = request.args.get("search", "").strip()
    kind, category_id = request.args.get("type"), request.args.get("category_id")
    if search: query = query.filter(Transaction.description.ilike(f"%{search[:100]}%"))
    if kind in ("income", "expense"): query = query.filter_by(type=kind)
    try:
        if category_id:
            category_number = int(category_id)
            if not 1 <= category_number <= 2147483647:
                raise ValueError
            query = query.filter_by(category_id=category_number)
        start = date.fromisoformat(request.args["from"]) if request.args.get("from") else None
        end = date.fromisoformat(request.args["to"]) if request.args.get("to") else None
        if start and end and start > end:
            return error("The start date must be on or before the end date.")
        if start:
            query = query.filter(Transaction.transaction_date >= start)
        if end:
            query = query.filter(Transaction.transaction_date <= end)
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 50))))
        if page > 2147483647:
            raise ValueError
    except ValueError:
        return error("Use ISO dates (YYYY-MM-DD) and valid category and pagination numbers.")
    ordering = request.args.get("sort", "date_desc")
    ordering_column = {"date_desc": Transaction.transaction_date.desc(), "date_asc": Transaction.transaction_date.asc(),
                       "amount_desc": Transaction.amount.desc(), "amount_asc": Transaction.amount.asc()}.get(ordering)
    if ordering_column is None: return error("Sort by date_desc, date_asc, amount_desc, or amount_asc.")
    pagination = query.order_by(ordering_column, Transaction.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({"items": [t.public() for t in pagination.items], "page": page, "pages": pagination.pages, "total": pagination.total})


@api.post("/transactions")
@jwt_required()
def create_transaction():
    uid, data = int(get_jwt_identity()), request.get_json(silent=True) or {}
    values, issue = transaction_values(data, uid)
    if issue: return error(issue)
    item = Transaction(user_id=uid, category_id=values["category"].id, amount=values["amount"], type=values["type"], transaction_date=values["date"], description=values["description"])
    db.session.add(item); db.session.commit()
    return jsonify(item.public()), 201


@api.put("/transactions/<int:item_id>")
@jwt_required()
def update_transaction(item_id):
    uid = int(get_jwt_identity())
    item = Transaction.query.filter_by(id=item_id, user_id=uid).first()
    if not item: return error("Transaction not found.", 404)
    values, issue = transaction_values(request.get_json(silent=True) or {}, uid, item)
    if issue: return error(issue)
    item.category_id, item.amount, item.type = values["category"].id, values["amount"], values["type"]
    item.transaction_date, item.description = values["date"], values["description"]
    db.session.commit()
    return jsonify(item.public())


@api.delete("/transactions/<int:item_id>")
@jwt_required()
def delete_transaction(item_id):
    item = Transaction.query.filter_by(id=item_id, user_id=int(get_jwt_identity())).first()
    if not item: return error("Transaction not found.", 404)
    db.session.delete(item); db.session.commit()
    return jsonify({"message": "Transaction deleted."})


def range_totals(uid, start, end):
    rows = db.session.query(Transaction.type, func.coalesce(func.sum(Transaction.amount), 0)).filter(Transaction.user_id == uid, Transaction.transaction_date >= start, Transaction.transaction_date < end).group_by(Transaction.type).all()
    totals = {kind: float(amount) for kind, amount in rows}
    return totals.get("income", 0), totals.get("expense", 0)


@api.get("/dashboard")
@jwt_required()
def dashboard():
    uid = int(get_jwt_identity())
    try: start, end, year, month = period_args()
    except ValueError as exc: return error(str(exc))
    analytics = FinancialAnalytics(uid, current_user().currency)
    totals, breakdown, _, transaction_count = analytics.totals(start, end)
    income, expenses = totals["income"], totals["expense"]
    if month is None:
        prev_start, prev_end = date(year - 1, 1, 1), start
    else:
        prev_start = date(start.year - (start.month == 1), start.month - 1 if start.month > 1 else 12, 1)
        prev_end = start
    p_income, p_expenses = range_totals(uid, prev_start, prev_end)
    scoped = analytics.transactions(start, end)
    grouped = sorted(breakdown["expense"].items(), key=lambda item: (-item[1], item[0]))
    recent = scoped.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).limit(6).all()
    annual_scope = scoped if month is None else analytics.transactions(date(year, 1, 1), date(year + 1, 1, 1))
    month_col = func.extract("month", Transaction.transaction_date)
    monthly_rows = annual_scope.with_entities(
        month_col, Transaction.type, func.sum(Transaction.amount),
    ).group_by(month_col, Transaction.type).all()
    months = [{"month": month_name[number], "income": 0, "expenses": 0} for number in range(1, 13)]
    for month_num, kind, total in monthly_rows:
        months[int(month_num) - 1]["income" if kind == "income" else "expenses"] = float(total)
    chart_months = enumerate(months, start=1) if month is None else [(month, months[month - 1])]
    trends = [{**values, "month": month_abbr[number]} for number, values in chart_months]
    balance = income - expenses
    return jsonify({"period": {"year": year, "month": month},
                    "date_filters": {"from": start.isoformat(), "to": (end - timedelta(days=1)).isoformat()},
                    "income": float(income), "expenses": float(expenses),
                    "balance": float(balance), "transaction_count": transaction_count,
                    "savings_rate": float(round(balance / income * 100, 1)) if income > 0 else 0,
                    "previous": {"income": p_income, "expenses": p_expenses},
                    "trend": trends, "months": months,
                    "categories": [{"name": name, "amount": float(value)} for name, value in grouped],
                    "recent": [transaction.public() for transaction, _ in recent]})


def budget_rows(uid, month, year):
    start, end = date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)
    budgets = Budget.query.filter_by(user_id=uid, budget_month=month, budget_year=year).all()
    spending = FinancialAnalytics(uid, "INR").spending_by_category_id(start, end) if budgets else {}
    return [budget.public(float(spending.get(budget.category_id, 0))) for budget in budgets]


@api.get("/budgets")
@jwt_required()
def list_budgets():
    today = date.today()
    try: month, year = int(request.args.get("month", today.month)), int(request.args.get("year", today.year))
    except ValueError: return error("Month and year must be numbers.")
    if not 1 <= month <= 12 or not 1900 <= year <= 9998: return error("Use a valid budget month and year.")
    return jsonify(budget_rows(int(get_jwt_identity()), month, year))


@api.post("/budgets")
@jwt_required()
def create_budget():
    uid, data = int(get_jwt_identity()), request.get_json(silent=True) or {}
    try:
        category_id, month, year = int(data.get("category_id")), int(data.get("month")), int(data.get("year"))
        amount = Decimal(str(data.get("amount")))
    except (TypeError, ValueError, InvalidOperation): return error("Enter a valid amount, category, month, and year.")
    cat = owned_category(category_id, uid, "expense")
    if (not cat or not amount.is_finite() or not Decimal("0.01") <= amount <= Decimal("9999999999.99")
            or not 1 <= month <= 12 or not 1900 <= year <= 9998):
        return error("Budget needs a valid expense category, amount, month, and year.")
    item = Budget.query.filter_by(user_id=uid, category_id=category_id, budget_month=month, budget_year=year).first()
    created = item is None
    if item: item.amount = amount.quantize(Decimal("0.01"))
    else:
        item = Budget(user_id=uid, category_id=category_id, amount=amount.quantize(Decimal("0.01")), budget_month=month, budget_year=year); db.session.add(item)
    db.session.commit()
    return jsonify(next(row for row in budget_rows(uid, month, year) if row["id"] == item.id)), 201 if created else 200


@api.delete("/budgets/<int:item_id>")
@jwt_required()
def delete_budget(item_id):
    item = Budget.query.filter_by(id=item_id, user_id=int(get_jwt_identity())).first()
    if not item: return error("Budget not found.", 404)
    db.session.delete(item); db.session.commit()
    return jsonify({"message": "Budget deleted."})


@api.get("/reports")
@jwt_required()
def reports():
    uid = int(get_jwt_identity())
    try: start, end, year, month = period_args()
    except ValueError as exc: return error(str(exc))
    grouped = db.session.query(Transaction.type, Category.name, func.sum(Transaction.amount), func.count(Transaction.id)).join(Category).filter(Transaction.user_id == uid, Transaction.transaction_date >= start, Transaction.transaction_date < end).group_by(Transaction.type, Category.name).order_by(func.sum(Transaction.amount).desc()).all()
    income, expenses = range_totals(uid, start, end)
    return jsonify({"year": year, "month": month, "income": income, "expenses": expenses,
                    "categories": [{"type": kind, "name": name, "amount": float(total), "count": count} for kind, name, total, count in grouped]})


@api.get("/reports/export")
@jwt_required()
def export_transactions():
    rows = Transaction.query.filter_by(user_id=int(get_jwt_identity())).order_by(Transaction.transaction_date.desc()).all()
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(["Date", "Type", "Category", "Amount", "Description"])
    for item in rows:
        writer.writerow([item.transaction_date.isoformat(), item.type, csv_text(item.category.name), str(item.amount), csv_text(item.description)])
    return Response(stream.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=smartspend-transactions.csv"})


def csv_text(value):
    prefixes = ("=", "+", "-", "@", "＝", "＋", "－", "＠")
    if value.lstrip().startswith(prefixes) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


FINANCE_DEFINITIONS = {
    "money": "Money is anything people commonly accept as payment for goods and services. It also gives us a way to compare prices and save purchasing power for later.",
    "inflation": "Inflation is a rise in the general level of prices over time. For example, if the same basket of groceries rises from ₹1,000 to ₹1,050, it costs 5% more and the same money buys less.",
    "finance": "Finance is the management of money. It includes earning, spending, saving, borrowing, and investing.",
    "personal finance": "Personal finance is how you manage your money, including your income, bills, savings, debt, and investments.",
    "income": "Income is money you receive, such as salary, freelance pay, or interest.",
    "expense": "An expense is money you spend, such as rent, groceries, or transport.",
    "budget": "A budget is a plan for how you will spend and save your income over a period.",
    "savings": "Savings is money you set aside for future needs or goals.",
    "savings rate": "Your savings rate is the percentage of income left after expenses. Divide net savings by total income and multiply by 100.",
    "debt": "Debt is money you owe and are expected to repay, sometimes with interest.",
    "interest": "Interest is the cost of borrowing money or the amount you earn on some savings.",
    "investment": "An investment is money put into an asset with the aim of earning a return over time.",
    "emergency fund": "An emergency fund is money you set aside for unexpected expenses or a loss of income.",
}

GENERAL_HELP = {
    "budgeting": "Budgeting means planning how to use your income. List your expected income, cover essential expenses, set aside savings, and review the plan regularly.",
    "income and expenses": "Income is money you receive. Expenses are money you spend. Subtract expenses from income to find how much is left.",
    "saving": "Start with a specific savings goal. Track spending, review recurring costs, and set aside an amount you can afford regularly.",
    "artificial intelligence": "Artificial intelligence (AI) is the field of building software that can do tasks such as recognizing speech, spotting patterns, or answering questions.",
    "machine learning": "Machine learning is a way to build AI by training software on examples so it can find patterns and make predictions on new data.",
    "python": "Python is a programming language with readable syntax. People use it to automate tasks, build websites, and analyze data.",
}


def assistant_language_reply(question, history, verified=None):
    groq_key = os.getenv("GROQ_API_KEY")
    key = groq_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return {}
    endpoint = "https://api.groq.com/openai/v1/chat/completions" if groq_key else "https://api.openai.com/v1/chat/completions"
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") if groq_key else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    system = (
        "Classify the last message using one of these intents: " + ", ".join(sorted(INTENTS)) +
        ". Return JSON with intent and answer. For GENERAL_CONVERSATION, answer helpfully in plain text. "
        "For personal financial requests return the intent and optionally a period as YYYY-MM, never guess amounts. "
        "For a mixed request, return the financial intent and a concept string containing only the general part. "
        "No account records are provided. Never request account credentials, produce SQL, or present guesses as account data."
    )
    if verified is not None:
        system = (
            "Return JSON with intent GENERAL_CONVERSATION and an answer string. Explain the requested concept "
            "or give a practical suggestion informed by the verified summary. Do not repeat the account totals; "
            "the application appends them separately. Do not add account facts or infer what caused a change. "
            "For inflation questions, explain that transaction totals alone do not measure price inflation."
        )
    content = {"question": question}
    if verified is None:
        content["previous_questions"] = history
    else:
        content["verified_summary"] = verified
    body = {"model": model, "response_format": {"type": "json_object"}, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(content)},
    ]}
    request_to_provider = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "SmartSpend/1.0",
    }, method="POST")
    try:
        with urllib.request.urlopen(request_to_provider, timeout=8) as response:
            result = json.loads(response.read())
        result = json.loads(result["choices"][0]["message"]["content"])
        if isinstance(result, dict) and isinstance(result.get("intent"), str) and result["intent"] in INTENTS:
            return result
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        current_app.logger.warning("SmartSpend chat provider unavailable")
    return {}


def general_chat_fallback(prompt):
    if re.fullmatch(r"(?:hi|hey|hello)(?: there)?(?:[,.! ]+how are you)?[.!?]*", prompt):
        return "Hi! I can help you review your income, expenses, and budgets."
    if re.search(r"what can you do|how can you help", prompt):
        return "I can answer finance questions, summarize your recorded income and expenses, review budgets, and compare months."
    if re.search(r"\b(?:what|define|explain)\b", prompt):
        definitions = {**FINANCE_DEFINITIONS, **{term: GENERAL_HELP[term] for term in (
            "artificial intelligence", "machine learning", "python",
        )}}
        for term, definition in sorted(definitions.items(), key=lambda item: -len(item[0])):
            if re.match(r"^(?:what (?:is|are)|define|explain) (?:a |an )?" + re.escape(term) + r"s?\b", prompt):
                return definition
    if re.search(r"\b(?:tell me|know) (?:a |any )?joke\b", prompt):
        return "Why did the computer go to the doctor? It had a virus."
    if re.search(r"50\s*/\s*30\s*/\s*20|50-30-20", prompt):
        return "The 50/30/20 rule suggests using 50% of take-home pay for needs, 30% for wants, and 20% for savings and extra debt payments. Adjust the split to fit your essential costs."
    if "budget" in prompt:
        return GENERAL_HELP["budgeting"]
    if "difference" in prompt and "income" in prompt and "expense" in prompt:
        return GENERAL_HELP["income and expenses"]
    if re.search(r"save (?:more )?money|reduce unnecessary spending|saving tips", prompt):
        return GENERAL_HELP["saving"]
    return None


def classify_chat(prompt):
    # Route explicit account actions locally. The provider interprets open-ended wording.
    clauses = re.split(r"(?:[,.?;]\s*|\band\s+)(?=(?:then\s+)?(?:show|compare|calculate|tell|analy[sz]e|how much|how it affects)\b)", prompt, maxsplit=1)
    if len(clauses) == 2 and re.match(r"^(?:explain|define|what (?:is|are))\b", clauses[0]):
        concept, account = clauses
        concept = re.sub(r"[,.?; ]+and\s*$", "", concept).strip(" ,.?!;")
        if re.search(r"\b(?:my|i|me)\b", account) and intent_for(account) != "GENERAL_CONVERSATION":
            return "MIXED_QUERY", account, concept
    intent = intent_for(prompt)
    if intent == "FINANCIAL_RECOMMENDATION":
        return "FINANCIAL_ADVICE", prompt, None
    if intent == "GENERAL_CONVERSATION":
        return "GENERAL_CHAT", prompt, None
    return "PERSONAL_FINANCE", prompt, None


@api.post("/chat/message")
@limiter.limit("30 per minute")
@jwt_required()
def chat_message():
    return handle_chat_message()


def handle_chat_message():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Send a question as JSON.")
    question = data.get("question")
    history = data.get("history", [])
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        return error("Enter a question from 1 to 1000 characters.")
    if not isinstance(history, list) or len(history) > 8 or any(
        not isinstance(turn, str) or len(turn) > 1000 for turn in history
    ):
        return error("The conversation context is invalid.")
    prompt = " ".join(question.casefold().split())
    route, prompt, concept = classify_chat(prompt)
    today = date.today()
    prior_periods = []
    prior_intent = None
    prior_prompt = ""
    prior_range = None
    category_context = []
    try:
        for turn in history:
            previous = " ".join(turn.casefold().split())
            try:
                inherited_year = prior_periods[-1].year if prior_periods else None
                previous_range = read_date_range(previous, today, inherited_year)
                found = [] if previous_range else read_periods(previous, today, inherited_year)
            except ValueError:
                continue
            for period in found:
                if period in prior_periods:
                    prior_periods.remove(period)
                prior_periods.append(period)
            previous_intent = intent_for(previous)
            if previous_range or found:
                prior_range = previous_range
            if previous_intent != "GENERAL_CONVERSATION":
                category_context.append((previous, bool(found or previous_range)))
            if previous_intent not in {"GENERAL_CONVERSATION", "CLARIFICATION_REQUIRED", "COMPARISON"}:
                category_drilldown = previous_intent == "CATEGORY_ANALYSIS" and prior_intent == "FINANCIAL_EXPENSE" and not found
                if not category_drilldown:
                    prior_intent, prior_prompt = previous_intent, previous
        inherited_year = prior_range[0].year if prior_range else prior_periods[-1].year if prior_periods else None
        selected_range = read_date_range(prompt, today, inherited_year)
        periods = [] if selected_range else read_periods(prompt, today, inherited_year)
    except ValueError:
        return jsonify({"answer": "Please enter a valid month and year, or a valid date range in YYYY-MM-DD format."})
    intent = intent_for(prompt)
    follow_up = bool(re.match(r"^(?:what about|how about|and)\b", prompt) or
                     (periods and intent == "GENERAL_CONVERSATION" and len(prompt.split()) <= 2))
    if follow_up and prior_intent and periods:
        intent = prior_intent
    if intent == "COMPARISON" and "both" in prompt and not periods:
        if len(prior_periods) < 2:
            return jsonify({"answer": "Which two months should I compare?"})
        periods = sorted(prior_periods[-2:])
        metric = {"FINANCIAL_INCOME": "income", "FINANCIAL_SAVINGS": "savings"}.get(prior_intent, "expenses")
        prompt += f" {metric}"
    if intent == "GENERAL_CONVERSATION":
        general_history = [turn for turn in history if classify_chat(" ".join(turn.casefold().split()))[0] == "GENERAL_CHAT"]
        result = assistant_language_reply(question, general_history)
        intent = result.get("intent", "GENERAL_CONVERSATION")
        if intent == "GENERAL_CONVERSATION":
            answer = result.get("answer")
            if re.search(r"\bmy\b.*\b(?:finances|account|financial history|balance|money)\b", prompt):
                return jsonify({"answer": "Which of your recorded income, expenses, savings, budgets, or transactions should I look up?"})
            fallback = general_chat_fallback(prompt)
            if isinstance(answer, str) and answer.strip():
                return jsonify({"answer": answer})
            if fallback:
                return jsonify({"answer": fallback})
            provider_enabled = bool(os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY"))
            detail = ("The AI provider didn't respond. Try again in a moment." if provider_enabled else
                      "Open-ended chat needs an AI provider configured on the server.")
            return jsonify({"answer": detail + " You can still ask about recorded income, expenses, savings, or budgets."})
        if not periods and isinstance(result.get("period"), str) and re.fullmatch(r"\d{4}-\d{2}", result["period"]):
            try:
                periods = read_periods(result["period"], today)
            except ValueError:
                return jsonify({"answer": "Which month and year do you mean?"})
        if isinstance(result.get("concept"), str) and 1 <= len(result["concept"].strip()) <= 1000:
            route, concept = "MIXED_QUERY", result["concept"].strip()
        elif intent == "FINANCIAL_RECOMMENDATION":
            route = "FINANCIAL_ADVICE"
    if intent == "CLARIFICATION_REQUIRED" and not (follow_up and (prior_periods or prior_range or prior_intent)):
        return jsonify({"answer": "Which income, expense, savings, or budget information would you like me to look up?"})
    if not periods and not selected_range and not re.search(r"\b(?:year|today|yesterday|total|all time|all recorded|trend|\d{4})\b", prompt):
        if intent not in {"COMPARISON", "FINANCIAL_PREDICTION"}:
            if prior_range:
                selected_range = prior_range
            else:
                periods = prior_periods[-1:]
    try:
        uid = int(get_jwt_identity())
        user = db.session.get(User, uid)
        if not user:
            return error("Account unavailable.", 401)
        service = FinancialAnalytics(uid, user.currency)
        categories = service.categories_in(prompt)
        category = categories[0] if categories else None
        comparison = categories if len(categories) > 1 and intent == "COMPARISON" else ()
        category_reference = bool(re.search(r"\bthat category\b", prompt))
        transaction_follow_up = intent == "TRANSACTION_SEARCH" and (
            category_reference or re.fullmatch(r"show(?: me)? (?:the|those) transactions[?!.]*", prompt)
        )
        if not category and (follow_up or transaction_follow_up):
            for previous, sets_period in reversed(category_context):
                category = service.category_in(previous)
                if category:
                    break
                if re.search(r"\bin which areas?\b|\bwhich category\b|\bwhere.*spend", previous):
                    if category_reference and ("most" in previous or "highest" in previous or "lowest" in previous):
                        bounds = selected_range[:2] if selected_range else (
                            (periods[-1], shift(periods[-1], 1)) if periods else (None, None)
                        )
                        expenses = service.totals(*bounds)[1]["expense"]
                        if expenses:
                            order = min if "lowest" in previous else max
                            category = order(sorted(expenses), key=expenses.get)
                    if category or not follow_up:
                        break
                if sets_period:
                    break
        if category_reference and not category:
            return jsonify({"answer": "Which spending category should I use?"})
        if intent == "CLARIFICATION_REQUIRED":
            if not categories:
                return jsonify({"answer": "Which spending category or month should I use?"})
            intent = "CATEGORY_ANALYSIS"
        if not category and re.search(r"\b(?:(?:spent|spend|spending) on\s+\w+|(?:grocery|groceries) spending)\b", prompt):
            return jsonify({"answer": NO_RECORDS})
        answer, display = answer_financial(
            service, intent, prompt, periods, today, category, selected_range, comparison
        )
        if route == "MIXED_QUERY":
            db.session.remove()
            summary = answer if current_app.config.get("AI_SHARE_FINANCIAL_SUMMARIES") and (
                not display or display.get("type") != "transactions"
            ) else None
            explanation = assistant_language_reply(concept, [], verified=summary).get("answer")
            if not isinstance(explanation, str) or not explanation.strip():
                explanation = general_chat_fallback(concept)
                if explanation and "inflation" in concept:
                    explanation += " Your transaction totals alone cannot show how much of a spending change came from inflation."
            explanation = explanation or "The AI provider is unavailable to explain the general part of this question."
            answer = f"{explanation}\n\nYour SmartSpend records\n{answer}"
        elif route == "FINANCIAL_ADVICE" and answer != NO_RECORDS and current_app.config.get("AI_SHARE_FINANCIAL_SUMMARIES"):
            db.session.remove()
            suggestion = assistant_language_reply(question, [], verified=answer).get("answer")
            if isinstance(suggestion, str) and suggestion.strip() and not re.search(r"\d", suggestion):
                answer = f"{answer}\n\nAdditional suggestion\n{suggestion}"
        return jsonify({"answer": answer, "display": display})
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning("SmartSpend chat database unavailable")
        return error("Your financial records are temporarily unavailable. Please try again.", 503)


def monthly_finance_answer(question, uid, start, previous_start):
    prompt = question.casefold()
    months = {
        name.casefold(): month
        for month in range(1, 13)
        for name in (month_name[month], month_abbr[month])
    }
    period = re.search(
        rf"\b(this month|last month|(?:{'|'.join(months)})(?:\s+\d{{4}})?)\b", prompt
    )
    if not period:
        return None
    words = set(re.findall(r"\w+", prompt[:period.start()] + " " + prompt[period.end():]))
    income_words = {"income", "earnings", "earn", "earned"}
    expense_words = {"expense", "expenses", "spending", "spend", "spent"}
    query_words = set(
        "what how much did do i my me we our have has is are was were in for of the and vs versus "
        "total totals monthly recorded show tell give please so far compare to with on".split()
    )
    spending_words = set("where which category categories breakdown by money more most top highest largest go went".split())
    spending_analysis = (
        bool(words & spending_words)
        and bool(words & (expense_words | {"money"}))
        and not words - (expense_words | query_words | spending_words)
    )
    if not spending_analysis and words - (income_words | expense_words | query_words):
        return None
    wants_income = bool(words & income_words)
    wants_expenses = bool(words & expense_words)
    if not (spending_analysis or wants_income or wants_expenses):
        return None

    label = period.group()
    if label == "this month":
        month_start = start
    elif label == "last month":
        month_start = previous_start
    else:
        month, *year = label.split()
        year = int(year[0]) if year else start.year
        if not 1 <= year <= 9999:
            return "Enter a year from 1 to 9999."
        month_start = date(year, months[month], 1)
    if month_start.year == 9999 and month_start.month == 12:
        return "December 9999 is outside the supported reporting range."
    month_end = month_start + timedelta(days=monthrange(month_start.year, month_start.month)[1])
    if spending_analysis:
        categories = expense_categories(uid, month_start, month_end)
        if not categories:
            return f"You have no recorded expenses for {month_start:%B %Y}."
        total = sum(amount for _, amount in categories)
        category, amount = categories[0]
        breakdown = ", ".join(f"{name} ₹{value:,.2f}" for name, value in categories[:3])
        return (
            f"In {month_start:%B %Y}, you spent the most on {category} "
            f"(₹{amount:,.2f}, {amount / total:.0%} of ₹{total:,.2f} in recorded expenses). "
            f"Top spending categories: {breakdown}."
        )
    income, expenses = range_totals(uid, month_start, month_end)
    amounts = []
    if wants_income:
        amounts.append(f"₹{income:,.2f} in income")
    if wants_expenses:
        amounts.append(f"₹{expenses:,.2f} in expenses")
    return f"For {month_start:%B %Y}, your recorded totals are {' and '.join(amounts)}."


def expense_categories(uid, start, end):
    total = func.sum(Transaction.amount)
    return db.session.query(Category.name, total).join(
        Transaction, Transaction.category_id == Category.id
    ).filter(
        Transaction.user_id == uid, Transaction.type == "expense",
        Transaction.transaction_date >= start, Transaction.transaction_date < end,
    ).group_by(Category.name).order_by(total.desc(), Category.name).all()


def finance_fallback(question, rows):
    prompt = " ".join(re.findall(r"\w+", question.casefold()))
    if prompt in {"where am i spending the most", "what is my top spending category", "what is my highest spending category"}:
        if not rows:
            return "You have no recorded expenses this month."
        category, amount = rows[0]
        return f"Your highest spending category this month is {category} at ₹{amount:,.2f}."
    if prompt in {"how can i save more", "how can i reduce my spending"}:
        if not rows:
            return "Add your expenses for this month to see which spending category you could review first."
        category, amount = rows[0]
        return f"Start by reviewing {category}, your largest expense category this month at ₹{amount:,.2f}. Look for purchases you can reduce or skip."
    return None


@api.post("/ai/ask")
@limiter.limit("30 per minute")
@jwt_required()
def ask_ai():
    if current_app.config.get("PRODUCTION") or not current_app.config.get("AI_SHARE_FINANCIAL_SUMMARIES"):
        return handle_chat_message()
    uid = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()
    if not question or len(question) > 1000: return error("Enter a question under 1000 characters.")
    if re.fullmatch(r"(?:hi|hello|hey)(?:\s+there)?[.!?]*", question, re.IGNORECASE):
        return jsonify({"answer": "Hi! I can help you review your income, expenses, and budgets. Try asking how much you spent last month."})
    definition = re.fullmatch(r"(?:what (?:is|are)|define|explain)\s+(?:(?:a|an)\s+)?(.+?)[.?!]*", question.casefold())
    if definition and definition[1] in FINANCE_DEFINITIONS:
        return jsonify({"answer": FINANCE_DEFINITIONS[definition[1]]})
    today = date.today(); start = today.replace(day=1)
    previous_start = date(start.year - (start.month == 1), 12 if start.month == 1 else start.month - 1, 1)
    answer = monthly_finance_answer(question, uid, start, previous_start)
    if answer:
        return jsonify({"answer": answer})
    income, expenses = range_totals(uid, start, today + timedelta(days=1))
    previous_income, previous_expenses = range_totals(uid, previous_start, start)
    rows = expense_categories(uid, start, today + timedelta(days=1))
    budgets = budget_rows(uid, today.month, today.year)
    groq_key = os.getenv("GROQ_API_KEY")
    api_key = groq_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        answer = finance_fallback(question, rows)
        return jsonify({"answer": answer or "The AI service is not configured. Try one of the suggested questions about your recorded spending."})
    recorded_year = func.extract("year", Transaction.transaction_date)
    recorded_month = func.extract("month", Transaction.transaction_date)
    monthly_rows = db.session.query(recorded_year, recorded_month, Transaction.type, func.sum(Transaction.amount)).filter(
        Transaction.user_id == uid, Transaction.transaction_date <= today
    ).group_by(recorded_year, recorded_month, Transaction.type).order_by(recorded_year.desc(), recorded_month.desc()).all()
    monthly_totals = {}
    for year, month, kind, amount in monthly_rows:
        period = f"{int(year):04d}-{int(month):02d}"
        monthly_totals.setdefault(period, {})[kind] = float(amount)
    try:
        endpoint = "https://api.groq.com/openai/v1/chat/completions" if groq_key else "https://api.openai.com/v1/chat/completions"
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b") if groq_key else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        payload = {"model": model, "response_format": {"type": "json_object"}, "messages": [
            {"role": "system", "content": (
                "Answer the user's question directly in plain language. Use general knowledge for "
                "questions that do not depend on their account. For account-specific questions, use "
                "only the supplied aggregates. For named months, use recorded_monthly_totals for "
                "the specified year, or the current year if the user omits the year. State the "
                "month and year. Missing months or transaction types mean no records, not a "
                "verified zero. Never substitute another month or invent amounts. Format account "
                "amounts in Indian rupees (₹). Return JSON with an answer string."
            )},
            {"role": "user", "content": json.dumps({"question": question, "as_of_date": today.isoformat(), "recorded_monthly_totals": monthly_totals, "month_to_date_income": income, "month_to_date_expenses": expenses, "previous_month_income": previous_income, "previous_month_expenses": previous_expenses, "expense_by_category": [{"category": n, "amount": float(a)} for n, a in rows], "budget_utilization": budgets})} ]}
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SmartSpend/1.0",
        }, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        response = json.loads(result["choices"][0]["message"]["content"] or "{}")
        answer = response.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("The AI service returned an empty or invalid answer.")
        db.session.add(AIInsight(user_id=uid, insight_type="question", period_start=start, period_end=today, content={"question": question, "answer": answer}))
        db.session.commit()
        return jsonify({"answer": answer})
    except Exception:
        db.session.rollback()
        current_app.logger.warning("SmartSpend AI request failed", exc_info=True)
        answer = finance_fallback(question, rows)
        return jsonify({"answer": answer or "The AI service is temporarily unavailable. Try one of the suggested questions about your recorded spending or try again later."})
