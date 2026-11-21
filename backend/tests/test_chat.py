from unittest.mock import patch
from urllib.error import URLError
from datetime import date
import io
import json
from urllib.error import HTTPError

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from test_health import TestConfig


@pytest.fixture
def chat(monkeypatch, request):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    app = create_app(TestConfig)
    app.config["AI_SHARE_FINANCIAL_SUMMARIES"] = getattr(request, "param", False)
    client = app.test_client()

    def register(email):
        result = client.post("/api/auth/register", json={
            "name": "Test User", "email": email, "password": "correct horse 71",
        })
        assert result.status_code == 201
        return {"Authorization": f"Bearer {result.json['access_token']}"}

    owner, other = register("owner@example.com"), register("other@example.com")
    records = [
        (owner, "Salary", "income", "1000.25", "2025-05-01"),
        (owner, "Food", "expense", "300.10", "2025-05-31"),
        (owner, "Shopping", "expense", "100.15", "2025-05-15"),
        (owner, "Food", "expense", "250", "2025-04-20"),
        (owner, "Salary", "income", "900", "2025-04-01"),
        (owner, "Food", "expense", "5", "2025-06-01"),
        (other, "Salary", "income", "99999", "2025-05-10"),
    ]
    categories = {
        headers["Authorization"]: {row["name"]: row["id"] for row in client.get("/api/categories", headers=headers).json}
        for headers in (owner, other)
    }
    for headers, name, kind, amount, day in records:
        response = client.post("/api/transactions", headers=headers, json={
            "amount": amount, "type": kind, "category_id": categories[headers["Authorization"]][name], "transaction_date": day,
        })
        assert response.status_code == 201, response.json

    def ask(question, history=(), headers=owner, **extra):
        return client.post("/api/chat/message", headers=headers, json={
            "question": question, "history": list(history), **extra,
        })

    assert client.post("/api/budgets", headers=owner, json={
        "category_id": categories[owner["Authorization"]]["Food"], "amount": "280", "month": 5, "year": 2025,
    }).status_code == 201
    return ask, other


def test_income_expenses_savings_and_categories(chat):
    ask, _ = chat
    assert "₹1,900.25" in ask("What is my total income?").json["answer"]
    may = ask("What was my income in May 2025?").json["answer"]
    assert "₹1,000.25" in may and "Salary" in may
    assert "₹400.25" in ask("How much did I spend in May 2025?").json["answer"]
    spending = ask("Where did I spend the money in the May 2025 more?").json
    assert "Food (74.98%" in spending["answer"]
    assert spending["display"]["rows"][0]["amount"] == "300.10"
    assert "₹100.15" in ask("How much did I spend on shopping in May 2025?").json["answer"]
    savings = ask("How much money did I save in May 2025?").json
    assert "₹600.00" in savings["answer"] and "59.99%" in savings["answer"]
    assert savings["display"]["type"] == "savings"


def test_transactions_reports_comparisons_and_context(chat):
    ask, _ = chat
    history = ["What were my expenses in May 2025?"]
    assert "Food" in ask("Where did I spend most?", history).json["answer"]
    april = ask("What about April?", [*history, "Where did I spend most?"]).json["answer"]
    assert "April 2025" in april and "₹250.00" in april
    comparison = ask("Compare both months", [*history, "What about April?"]).json
    assert "₹150.25" in comparison["answer"]
    assert "₹150.25" in ask("Compare April and May 2025").json["answer"]
    assert comparison["display"]["type"] == "comparison"
    transactions = ask("Show all my transactions from May 2025").json["display"]["rows"]
    assert [row["date"] for row in transactions] == ["2025-05-31", "2025-05-15", "2025-05-01"]
    assert "₹1,000.25" in ask("What was my biggest transaction in May 2025?").json["answer"]
    assert "₹1,000.25" in ask("What was my highest income month?").json["answer"]
    report = ask("Analyze my May 2025 spending").json["answer"]
    for text in ("Average daily spending", "Largest transaction", "previous month", "Suggestion"):
        assert text in report


def test_budget_trends_prediction_and_recommendations(chat):
    ask, _ = chat

    class July2025(date):
        @classmethod
        def today(cls):
            return cls(2025, 7, 12)

    with patch("app.api.date", July2025):
        budget = ask("Show my budgets in May").json["answer"]
        assert "₹20.10 over budget" in budget
        assert "₹20.10 over" in ask("Am I spending too much on Food in May?").json["answer"]
        trend = ask("Compare my spending over the last three months").json
        assert trend["display"]["type"] == "trend"
        assert [row["expenses"] for row in trend["display"]["rows"]] == ["250.00", "400.25", "5.00"]
        forecast = ask("Predict my next month's expenses").json["answer"]
        assert "August 2025: ₹218.42" in forecast
        assert "Food" in ask("Give me money-saving recommendations").json["answer"]


def test_validation_isolation_and_database_errors(chat):
    ask, other = chat
    assert ask("What is my income?", headers={}).status_code == 401
    assert ask(None).status_code == 400
    assert ask("What is my income?", ["x"] * 9).status_code == 400
    assert "valid month and year" in ask("What is my income for 2025-13?").json["answer"]
    assert "couldn't find" in ask("What was my income in March 2025?").json["answer"]
    attack = ask("Show my transactions for May 2025'; DROP TABLE transactions; --", user_id=2).json
    assert "₹99,999.00" not in str(attack)
    assert len(attack["display"]["rows"]) == 3
    assert "₹99,999.00" in ask("What is my total income?", headers=other, user_id=1).json["answer"]
    assert "couldn't find" in ask("How much did I spend in May 2025?", headers=other).json["answer"]
    with patch("app.api.FinancialAnalytics.totals", side_effect=SQLAlchemyError):
        assert ask("What is my total income?").status_code == 503


def test_provider_conversation_routing_and_outage(chat, monkeypatch):
    ask, _ = chat
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("app.api.assistant_language_reply", return_value={
        "intent": "GENERAL_CONVERSATION", "answer": "I am here to help.",
    }) as provider, patch("app.api.FinancialAnalytics") as analytics:
        assert ask("How are you?").json["answer"] == "I am here to help."
        provider.assert_called_once()
        analytics.assert_not_called()
    with patch("app.api.assistant_language_reply", return_value={"intent": "FINANCIAL_INCOME", "period": "2025-05"}):
        assert "₹1,000.25" in ask("What came in?").json["answer"]
    with patch("app.api.urllib.request.urlopen", side_effect=URLError("offline")) as provider:
        assert "Finance is the management" in ask("What is finance?").json["answer"]
        provider.reset_mock()
        assert "₹1,000.25" in ask("What was my income in May 2025?").json["answer"]
        provider.assert_not_called()


def test_general_offline_answers_do_not_query_financial_records(chat):
    ask, _ = chat
    with patch("app.api.FinancialAnalytics") as analytics:
        for question, expected in (
            ("What is money?", "Money is anything"),
            ("Explain artificial intelligence.", "Artificial intelligence (AI)"),
            ("What is machine learning?", "Machine learning"),
            ("Explain Python in simple words.", "Python is a programming language"),
            ("Hello.", "Hi!"),
            ("Tell me a joke.", "computer"),
            ("Explain inflation with an example.", "5%"),
        ):
            assert expected in ask(question).json["answer"]
        assert "configured on the server" in ask("Explain photosynthesis.").json["answer"]
        analytics.assert_not_called()


@pytest.mark.parametrize("chat,shares_data", [(False, False), (True, True)], indirect=["chat"])
def test_mixed_chat_uses_verified_user_totals(chat, shares_data, monkeypatch):
    ask, other = chat
    question = "Explain inflation and show my expenses in May 2025."
    result = ask(question).json["answer"]
    assert "Inflation is" in result and "₹400.25" in result
    assert "couldn't find" in ask(question, headers=other).json["answer"]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    provider_response = {"choices": [{"message": {"content": json.dumps({
        "intent": "GENERAL_CONVERSATION", "answer": "Inflation means prices are rising.",
    })}}]}
    with patch("app.api.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(provider_response).encode())) as provider:
        result = ask(question).json["answer"]
        assert "Inflation means prices are rising." in result and "₹400.25" in result
        body = json.loads(provider.call_args.args[0].data)
        context = json.loads(body["messages"][-1]["content"])
        expected = {"verified_summary": "Expenses for May 2025: ₹400.25"} if shares_data else {"previous_questions": []}
        assert context == {"question": "explain inflation", **expected}


def test_invalid_key_timeout_and_deterministic_finance_routes(chat, monkeypatch):
    ask, _ = chat
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    failures = [HTTPError("https://example.com", 401, "Unauthorized", None, None), TimeoutError()]
    for failure in failures:
        with patch("app.api.urllib.request.urlopen", side_effect=failure) as provider:
            assert "Money is anything" in ask("What is money?").json["answer"]
            assert "provider didn't respond" in ask("Tell me about Jupiter.").json["answer"]
            provider.reset_mock()
            assert "₹1,900.25" in ask("What is my total income?").json["answer"]
            provider.assert_not_called()
    class May31(date):
        @classmethod
        def today(cls):
            return cls(2025, 5, 31)

    with patch("app.api.date", May31):
        assert "₹300.10" in ask("How much did I spend today?").json["answer"]
        assert "₹150.25" in ask("Compare this month with last month.").json["answer"]
        result = ask("What are my top five expenses?").json
        assert [row["display"] for row in result["display"]["rows"]] == ["₹300.10", "₹250.00", "₹100.15", "₹5.00"]


def test_september_category_and_transaction_questions(monkeypatch):
    from app import db
    from app.models import Category

    class October15(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 15)

    monkeypatch.setattr("app.api.date", October15)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    app = create_app(TestConfig)
    client = app.test_client()

    def register(email):
        response = client.post("/api/auth/register", json={
            "email": email, "name": "Test User", "password": "correct horse 71",
        })
        return {"Authorization": f"Bearer {response.json['access_token']}"}

    def ask(question, history=(), headers=None):
        response = client.post("/api/chat/message", headers=headers or owner, json={
            "question": question, "history": list(history),
        })
        assert response.status_code == 200, response.json
        return response.json

    owner, other = register("september@example.com"), register("september-other@example.com")
    created = client.post("/api/categories", headers=owner, json={"name": "Clothing", "type": "expense"})
    assert created.status_code == 201
    categories = {row["name"]: row["id"] for row in client.get("/api/categories", headers=owner).json}
    records = [
        ("Food", "expense", "100.25", "2026-09-01", "Groceries"),
        ("Food", "expense", "100.25", "2026-09-01", "Groceries"),
        ("Clothing", "expense", "300", "2026-09-30", "Coat"),
        ("Shopping", "expense", "599.50", "2026-09-15", "Supplies"),
        ("Salary", "income", "2000", "2026-09-28", "Payroll"),
        ("Food", "expense", "100", "2026-05-01", "Lunch"),
        ("Food", "expense", "40", "2026-10-01", "Dinner"),
        ("Bills", "expense", "10", "2026-10-15", "Utility"),
        ("Salary", "income", "500", "2026-08-01", "Payroll"),
    ]
    for name, kind, amount, day, description in records:
        response = client.post("/api/transactions", headers=owner, json={
            "category_id": categories[name], "type": kind, "amount": amount,
            "transaction_date": day, "description": description,
        })
        assert response.status_code == 201, response.json
    for name, amount in (("Shopping", "400"), ("Food", "300")):
        assert client.post("/api/budgets", headers=owner, json={
            "category_id": categories[name], "amount": amount, "month": 9, "year": 2026,
        }).status_code == 201

    area_question = "In which areas did I spend my money in September?"
    report = ask(area_question)
    assert report["display"]["summary"] == {
        "display": "₹1,100.00", "count": 4, "percentage": "100.00%", "partial": False,
    }
    assert [(row["name"], row["display"], row["count"], row["percentage"]) for row in report["display"]["rows"]] == [
        ("Shopping", "₹599.50", 1, "54.50%"),
        ("Clothing", "₹300.00", 1, "27.27%"),
        ("Food", "₹200.50", 2, "18.23%"),
    ]
    assert "Average expense: ₹275.00" in report["answer"] and "Lowest spending category: Food" in report["answer"]
    assert "₹200.50" in ask("How much did I spend on food in September?")["answer"]
    assert "₹300.00" in ask("How much did I spend on clothes in September?")["answer"]
    assert "Highest spending category: Shopping" in ask("Which category has the highest spending?")["answer"]
    assert "₹50.00" in ask("Show my monthly expense breakdown.")["answer"]
    assert "₹1,000.00" in ask("Compare May and September expenses.")["answer"]
    september = ask("Show all my September transactions.")["display"]["rows"]
    assert len(september) == 5 and september[0]["description"] == "Coat"
    combined = ask("What is my total income and expense?")["answer"]
    assert "Income: ₹2,500.00" in combined and "Expenses: ₹1,250.00" in combined
    assert "Net savings: ₹1,250.00" in ask("How much money did I save?")["answer"]
    assert [row["display"] for row in ask("What were my top five transactions?")["display"]["rows"]] == [
        "₹2,000.00", "₹599.50", "₹500.00", "₹300.00", "₹100.25",
    ]
    assert ask("How many transactions did I make in September?")["answer"].endswith("5.")
    budget = ask("Which categories exceeded my budget?", [area_question])["answer"]
    assert "Shopping" in budget and "₹199.50 over budget" in budget and "Food" not in budget
    last_month = "In which area did I spend the most last month?"
    assert "Highest spending category: Shopping" in ask(last_month)["answer"]
    referenced = ask("Show me the transactions for that category.", [last_month])["display"]["rows"]
    assert [row["description"] for row in referenced] == ["Supplies"]

    history = ["How much did I spend in September?", "In which areas?", "What about food?"]
    assert "₹1,100.00" in ask(history[1], history[:1])["answer"]
    assert "₹200.50" in ask(history[2], history[:2])["answer"]
    assert [row["description"] for row in ask("Show the transactions.", history)["display"]["rows"]] == ["Groceries", "Groceries"]
    assert "18.23%" in ask("What percentage of my expenses went to Food in September?")["answer"]
    assert len(ask("Compare my food and shopping expenses in September.")["display"]["rows"]) == 2
    assert "₹1,100.00 in September" in ask("Which month did I spend the most?")["answer"]
    assert "Utility" == ask("What was my smallest transaction?")["display"]["rows"][0]["description"]
    assert ["Payroll"] == [row["description"] for row in ask("Show transactions above ₹1,000.")["display"]["rows"]]
    assert ["Coat", "Payroll"] == [
        row["description"] for row in ask("Show transactions from 15 September to September 30, 2026.")["display"]["rows"][:2]
    ]
    assert "₹350.00" in ask("How much did I spend in the last 30 days?")["answer"]
    assert "valid date range" in ask("Show transactions from 2026-10-01 to 2026-09-01.")["answer"]
    assert "couldn't find" in ask("Show my November expenses.")["answer"]
    assert "couldn't find" in ask("Show my August expenses.")["answer"]
    assert "couldn't find" in ask("How much did I spend on clothes in May?")["answer"]
    assert "couldn't find" in ask(area_question, headers=other)["answer"]
    assert client.post("/api/transactions", headers=owner, json={
        "category_id": categories["Food"], "type": "expense", "amount": "-10", "transaction_date": "2026-09-20",
    }).status_code == 400
    with app.app_context():
        db.session.get(Category, categories["Clothing"]).name = ""
        db.session.commit()
    assert "Uncategorized" in ask(area_question)["answer"]
