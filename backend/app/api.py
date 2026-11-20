import csv
import smtplib
import io
import json
import os
import urllib.error
import urllib.request
from email.message import EmailMessage
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request, Response
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from sqlalchemy import func
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app import db, limiter
from app.models import AIInsight, Budget, Category, Transaction, User

api = Blueprint("api", __name__, url_prefix="/api")
INCOME = ["Salary", "Freelance", "Business", "Investments", "Other Income"]
EXPENSE = ["Food", "Shopping", "Travel", "Rent", "Bills", "Healthcare", "Education", "Entertainment", "Other Expenses"]


def error(message, status=400):
    return jsonify({"error": message}), status


def current_user():
    return db.session.get(User, int(get_jwt_identity()))


def owned_category(category_id, user_id, kind=None):
    category = db.session.get(Category, category_id)
    if not category or category.user_id not in (None, user_id) or (kind and category.type != kind):
        return None
    return category


def period_args():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
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
    if len(name) < 2 or len(name) > 120 or "@" not in email or len(email) > 254:
        return error("Enter a valid name and email.")
    if not isinstance(password, str) or len(password) < 8:
        return error("Password must contain at least 8 characters.")
    if User.query.filter_by(email=email).first():
        return error("An account with this email already exists.", 409)
    user = User(name=name, email=email, currency="INR")
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    if not Category.query.filter(Category.user_id.is_(None)).first():
        db.session.add_all([Category(user_id=user.id, name=n, type="income") for n in INCOME] + [Category(user_id=user.id, name=n, type="expense") for n in EXPENSE])
    db.session.commit()
    return jsonify({"user": user.public(), "access_token": create_access_token(identity=str(user.id))}), 201


@api.post("/auth/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=str(data.get("email", "")).strip().lower()).first()
    if not user or not user.check_password(data.get("password", "")):
        return error("Email or password is incorrect.", 401)
    return jsonify({"user": user.public(), "access_token": create_access_token(identity=str(user.id))})


@api.post("/auth/forgot-password")
@limiter.limit("4 per hour")
def forgot_password():
    email = str((request.get_json(silent=True) or {}).get("email", "")).strip().lower()
    user = User.query.filter_by(email=email).first() if email else None
    # Respond identically whether the account exists or mail is configured.
    if user and current_app.config.get("SMTP_HOST") and current_app.config.get("SMTP_USER"):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        token = serializer.dumps(user.email, salt="smartspend-password-reset")
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
        except Exception:
            current_app.logger.exception("Password reset email could not be sent")
    return jsonify({"message": "If an account exists and email delivery is configured, a reset link will be sent."})


@api.post("/auth/reset-password")
@limiter.limit("5 per hour")
def reset_password():
    data = request.get_json(silent=True) or {}
    token, password = data.get("token", ""), data.get("password", "")
    if not isinstance(password, str) or len(password) < 8:
        return error("Password must contain at least 8 characters.")
    try:
        email = URLSafeTimedSerializer(current_app.config["SECRET_KEY"]).loads(token, salt="smartspend-password-reset", max_age=1800)
    except (BadSignature, SignatureExpired):
        return error("This reset link is invalid or expired. Request a new one.", 400)
    user = User.query.filter_by(email=email).first()
    if not user: return error("This reset link is invalid or expired.", 400)
    user.set_password(password); db.session.commit()
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
    if len(name) < 2 or "@" not in email or len(currency) != 3:
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
    if not isinstance(new, str) or len(new) < 8:
        return error("New password must contain at least 8 characters.")
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
    if not amount.is_finite() or amount <= 0 or amount > Decimal("9999999999.99") or kind not in ("income", "expense"):
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
    if category_id and category_id.isdigit(): query = query.filter_by(category_id=int(category_id))
    try:
        if request.args.get("from"): query = query.filter(Transaction.transaction_date >= date.fromisoformat(request.args["from"]))
        if request.args.get("to"): query = query.filter(Transaction.transaction_date <= date.fromisoformat(request.args["to"]))
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 50))))
    except ValueError:
        return error("Use ISO dates (YYYY-MM-DD) and whole-number pagination values.")
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
    income, expenses = range_totals(uid, start, end)
    if month is None:
        prev_start, prev_end = date(year - 1, 1, 1), start
    else:
        prev_start = date(start.year - (start.month == 1), start.month - 1 if start.month > 1 else 12, 1)
        prev_end = start
    p_income, p_expenses = range_totals(uid, prev_start, prev_end)
    grouped = db.session.query(Category.name, func.sum(Transaction.amount)).join(Transaction, Transaction.category_id == Category.id).filter(Transaction.user_id == uid, Transaction.type == "expense", Transaction.transaction_date >= start, Transaction.transaction_date < end).group_by(Category.name).order_by(func.sum(Transaction.amount).desc()).all()
    recent = Transaction.query.filter_by(user_id=uid).order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).limit(6).all()
    year_start, year_end = date(year, 1, 1), date(year + 1, 1, 1)
    month_col = func.extract("month", Transaction.transaction_date)
    monthly_rows = db.session.query(month_col, Transaction.type, func.sum(Transaction.amount)).filter(Transaction.user_id == uid, Transaction.transaction_date >= year_start, Transaction.transaction_date < year_end).group_by(month_col, Transaction.type).all()
    trends = [{"month": date(year, m, 1).strftime("%b"), "income": 0, "expenses": 0} for m in range(1, 13)]
    for month_num, kind, total in monthly_rows:
        if month_num:
            trends[int(month_num) - 1]["income" if kind == "income" else "expenses"] = float(total)
    return jsonify({"period": {"year": year, "month": month}, "income": income, "expenses": expenses, "balance": income - expenses,
                    "savings_rate": round((income - expenses) / income * 100, 1) if income else 0,
                    "previous": {"income": p_income, "expenses": p_expenses},
                    "trend": trends,
                    "categories": [{"name": name, "amount": float(value)} for name, value in grouped],
                    "recent": [t.public() for t in recent]})


def budget_rows(uid, month, year):
    start, end = date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)
    budgets = Budget.query.filter_by(user_id=uid, budget_month=month, budget_year=year).all()
    return [b.public(float(db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(Transaction.user_id == uid, Transaction.category_id == b.category_id, Transaction.type == "expense", Transaction.transaction_date >= start, Transaction.transaction_date < end).scalar())) for b in budgets]


@api.get("/budgets")
@jwt_required()
def list_budgets():
    today = date.today()
    try: month, year = int(request.args.get("month", today.month)), int(request.args.get("year", today.year))
    except ValueError: return error("Month and year must be numbers.")
    if not 1 <= month <= 12: return error("Month must be from 1 to 12.")
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
    if not cat or not amount.is_finite() or amount <= 0 or not 1 <= month <= 12: return error("Budget needs a valid expense category and positive amount.")
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
    return jsonify({"year": year, "month": month, "income": range_totals(uid, start, end)[0], "expenses": range_totals(uid, start, end)[1],
                    "categories": [{"type": kind, "name": name, "amount": float(total), "count": count} for kind, name, total, count in grouped]})


@api.get("/reports/export")
@jwt_required()
def export_transactions():
    rows = Transaction.query.filter_by(user_id=int(get_jwt_identity())).order_by(Transaction.transaction_date.desc()).all()
    stream = io.StringIO(); writer = csv.writer(stream)
    writer.writerow(["Date", "Type", "Category", "Amount", "Description"])
    for item in rows: writer.writerow([item.transaction_date.isoformat(), item.type, item.category.name, str(item.amount), item.description])
    return Response(stream.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=smartspend-transactions.csv"})


@api.post("/ai/ask")
@jwt_required()
def ask_ai():
    uid = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()
    if not question or len(question) > 1000: return error("Enter a question under 1000 characters.")
    today = date.today(); start = today.replace(day=1)
    income, expenses = range_totals(uid, start, today + timedelta(days=1))
    previous_start = date(start.year - (start.month == 1), 12 if start.month == 1 else start.month - 1, 1)
    previous_income, previous_expenses = range_totals(uid, previous_start, start)
    rows = db.session.query(Category.name, func.sum(Transaction.amount)).join(Transaction, Transaction.category_id == Category.id).filter(Transaction.user_id == uid, Transaction.type == "expense", Transaction.transaction_date >= start, Transaction.transaction_date <= today).group_by(Category.name).order_by(func.sum(Transaction.amount).desc()).all()
    budgets = budget_rows(uid, today.month, today.year)
    if not os.getenv("OPENAI_API_KEY"):
        highest = f" Your highest spending category is {rows[0][0]} at ₹{float(rows[0][1]):,.2f}." if rows else " I don’t have expense entries for this month yet."
        return jsonify({"answer": f"This month so far, income is ₹{income:,.2f} and expenses are ₹{expenses:,.2f}.{highest} AI-generated advice is unavailable until an API key is configured."})
    try:
        payload = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "response_format": {"type": "json_object"}, "messages": [
            {"role": "system", "content": "You are a finance helper. Use only the user's supplied aggregates. Never invent transactions or amounts. Return JSON with an answer string."},
            {"role": "user", "content": json.dumps({"question": question, "month_to_date_income": income, "month_to_date_expenses": expenses, "previous_month_income": previous_income, "previous_month_expenses": previous_expenses, "expense_by_category": [{"category": n, "amount": float(a)} for n, a in rows], "budget_utilization": budgets})} ]}
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        response = json.loads(result["choices"][0]["message"]["content"] or "{}")
        answer = str(response.get("answer", "I could not prepare an answer right now."))
        db.session.add(AIInsight(user_id=uid, insight_type="question", period_start=start, period_end=today, content={"question": question, "answer": answer}))
        db.session.commit()
        return jsonify({"answer": answer})
    except Exception:
        return jsonify({"answer": f"I can’t reach the AI service right now. Your month-to-date expenses total ₹{expenses:,.2f}. Please try again later."})
