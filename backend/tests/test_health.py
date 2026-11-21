from datetime import date
import io
import json
from unittest.mock import patch
from urllib.error import URLError

from app import create_app, db
from app.api import password_reset_token
from app.models import User


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    JWT_SECRET_KEY = "test-jwt-secret-key-that-is-over-32-characters-long"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_ACCESS_TOKEN_EXPIRES = 3600
    CORS_ORIGINS = ["http://localhost:5173"]
    AUTO_CREATE_TABLES = True
    RATELIMIT_STORAGE_URI = "memory://"


def test_health_endpoint_reports_service_status():
    client = create_app(TestConfig).test_client()
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "smartspend-api"}


def test_registration_login_and_user_specific_transactions():
    client = create_app(TestConfig).test_client()
    registered = client.post("/api/auth/register", json={"name": "Alex Example", "email": "alex@example.com", "password": "correct horse 71"})
    assert registered.status_code == 201
    token = registered.json["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    categories = client.get("/api/categories", headers=headers).json
    food = next(c for c in categories if c["name"] == "Food")
    created = client.post("/api/transactions", headers=headers, json={"amount": "125.50", "type": "expense", "category_id": food["id"], "transaction_date": "2026-11-20", "description": "Lunch"})
    assert created.status_code == 201
    dashboard = client.get("/api/dashboard?year=2026&month=11", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json["expenses"] == 125.5
    assert dashboard.json["balance"] == -125.5

    other = client.post("/api/auth/register", json={"name": "Other Person", "email": "other@example.com", "password": "correct horse 72"})
    other_headers = {"Authorization": f"Bearer {other.json['access_token']}"}
    forbidden_record = client.put(f"/api/transactions/{created.json['id']}", headers=other_headers, json={})
    assert forbidden_record.status_code == 404


def test_login_rejects_wrong_password():
    client = create_app(TestConfig).test_client()
    client.post("/api/auth/register", json={"name": "Alex Example", "email": "alex@example.com", "password": "correct horse 71"})
    response = client.post("/api/auth/login", json={"email": "alex@example.com", "password": "wrong password"})
    assert response.status_code == 401


def test_budget_upsert_and_password_reset_token():
    app = create_app(TestConfig)
    client = app.test_client()
    registered = client.post("/api/auth/register", json={"name": "Budget User", "email": "budget@example.com", "password": "correct horse 73"})
    headers = {"Authorization": f"Bearer {registered.json['access_token']}"}
    categories = client.get("/api/categories", headers=headers).json
    food = next(c for c in categories if c["name"] == "Food")
    first = client.post("/api/budgets", headers=headers, json={"category_id": food["id"], "amount": "5000", "month": 11, "year": 2026})
    updated = client.post("/api/budgets", headers=headers, json={"category_id": food["id"], "amount": "6000", "month": 11, "year": 2026})
    assert first.status_code == 201
    assert updated.status_code == 200
    assert len(client.get("/api/budgets?month=11&year=2026", headers=headers).json) == 1
    assert updated.json["amount"] == 6000

    with app.app_context():
        token = password_reset_token(db.session.get(User, registered.json["user"]["id"]))
    reset = client.post("/api/auth/reset-password", json={"token": token, "password": "new password 74"})
    assert reset.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/reset-password", json={"token": token, "password": "new password 75"}).status_code == 400
    assert client.post("/api/auth/login", json={"email": "budget@example.com", "password": "new password 74"}).status_code == 200


def test_assistant_fallback_answers_the_question(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    app = create_app(TestConfig)
    app.config["AI_SHARE_FINANCIAL_SUMMARIES"] = True
    client = app.test_client()
    registered = client.post("/api/auth/register", json={"name": "Alex Example", "email": "alex@example.com", "password": "correct horse 71"})
    headers = {"Authorization": f"Bearer {registered.json['access_token']}"}
    food = next(c for c in client.get("/api/categories", headers=headers).json if c["name"] == "Food")
    created = client.post("/api/transactions", headers=headers, json={
        "amount": "125.50", "type": "expense", "category_id": food["id"],
        "transaction_date": date.today().isoformat(),
    })
    assert created.status_code == 201

    salary = next(c for c in client.get("/api/categories", headers=headers).json if c["name"] == "Salary")
    historical_date = date(date.today().year - 1, 9, 15)
    historical = client.post("/api/transactions", headers=headers, json={
        "amount": "47000", "type": "income", "category_id": salary["id"],
        "transaction_date": historical_date.isoformat(),
    })
    assert historical.status_code == 201
    may = date(date.today().year - 1, 5, 15)
    for category, amount in ((food, "75"), (next(
        c for c in client.get("/api/categories", headers=headers).json if c["name"] == "Travel"
    ), "25")):
        response = client.post("/api/transactions", headers=headers, json={
            "amount": amount, "type": "expense", "category_id": category["id"],
            "transaction_date": may.isoformat(),
        })
        assert response.status_code == 201

    def ask(question):
        response = client.post("/api/ai/ask", headers=headers, json={"question": question})
        assert response.status_code == 200
        return response.json["answer"]

    assert "₹125.50 in expenses" in ask("How much have I spent this month?")
    monthly_question = f"Show my income and expenses for September {historical_date.year}"
    monthly_answer = f"For September {historical_date.year}, your recorded totals are ₹47,000.00 in income and ₹0.00 in expenses."
    assert ask(monthly_question) == monthly_answer
    assert f"For May {date.today().year}" in ask("What is the income in May?")
    may_question = f"Where did I spend the money in the May {may.year} more?"
    may_analysis = ask(may_question)
    assert "Food (₹75.00, 75% of ₹100.00" in may_analysis
    assert "Travel ₹25.00" in may_analysis
    assert "highest spending category this month is Food" in ask("Where am I spending the most?")
    assert "Start by reviewing Food" in ask("How can I save more?")
    assert "AI service is not configured" in ask("What were my restaurant expenses in July?")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("app.api.urllib.request.urlopen", side_effect=URLError("offline")) as provider:
        assert ask("Hi!").startswith("Hi!")
        assert ask("What is finance?").startswith("Finance is the management of money.")
        assert ask(may_question) == may_analysis
        assert ask(monthly_question) == monthly_answer
        assert "₹125.50" in ask("How much have I spent this month?")
        provider.assert_not_called()
        assert "temporarily unavailable" in ask("What were my restaurant expenses in July?")

    question = "What is the difference between a debit card and a credit card?"
    answer = "A debit card uses money from your account. A credit card borrows against a credit limit."
    provider_body = {"choices": [{"message": {"content": json.dumps({"answer": answer})}}]}
    with patch("app.api.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(provider_body).encode())) as provider:
        assert ask(question) == answer
        payload = json.loads(provider.call_args.args[0].data)
        context = json.loads(payload["messages"][-1]["content"])
        assert context["question"] == question
        assert context["recorded_monthly_totals"][historical_date.strftime("%Y-%m")] == {"income": 47000.0}

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    with patch("app.api.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(provider_body).encode())) as provider:
        assert ask(question) == answer
        outgoing = provider.call_args.args[0]
        assert outgoing.full_url == "https://api.groq.com/openai/v1/chat/completions"
        assert outgoing.get_header("Authorization") == "Bearer test-groq-key"
        assert json.loads(outgoing.data)["model"] == "openai/gpt-oss-20b"
