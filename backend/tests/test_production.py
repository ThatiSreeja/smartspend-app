import csv
import io
import os
from pathlib import Path
from datetime import timedelta

import pytest
from flask_migrate import upgrade
from flask_jwt_extended import create_access_token
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app import create_app, db, validate_production
from app.models import User
from test_health import TestConfig


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_migrations_preserve_existing_rows_and_foreign_keys(tmp_path):
    class MigrationConfig(TestConfig):
        AUTO_CREATE_TABLES = False
        SQLALCHEMY_DATABASE_URI = os.getenv("SMARTSPEND_MIGRATION_TEST_URL") or f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"

    app = create_app(MigrationConfig)
    with app.app_context():
        if db.engine.dialect.name != "sqlite":
            assert make_url(MigrationConfig.SQLALCHEMY_DATABASE_URI).database == "smartspend_test"
            assert not inspect(db.engine).get_table_names(), "The migration test database must be empty."
        upgrade(directory=str(MIGRATIONS), revision="d33d1cbb8f8c")
        db.session.execute(text(
            "INSERT INTO users (id, name, email, password_hash, currency, created_at) "
            "VALUES (1, 'Audit User', 'audit@example.com', 'test-fixture', 'INR', '2026-01-01 00:00:00')"
        ))
        db.session.execute(text(
            "INSERT INTO categories (id, user_id, name, type, is_default) VALUES (1, 1, 'Food', 'expense', false)"
        ))
        db.session.execute(text(
            "INSERT INTO transactions (id, user_id, category_id, amount, type, description, transaction_date, created_at) "
            "VALUES (1, 1, 1, 12.50, 'expense', 'Lunch', '2026-01-01', '2026-01-01 00:00:00')"
        ))
        db.session.execute(text(
            "INSERT INTO budgets (id, user_id, category_id, amount, budget_month, budget_year) VALUES (1, 1, 1, 50, 1, 2026)"
        ))
        db.session.commit()
        upgrade(directory=str(MIGRATIONS))
        upgrade(directory=str(MIGRATIONS))
        for table in ("users", "categories", "transactions", "budgets"):
            assert db.session.execute(text(f"SELECT updated_at FROM {table} WHERE id = 1")).scalar()
        assert db.session.execute(text("SELECT amount FROM transactions WHERE id = 1")).scalar() == 12.50
        assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0e3d0d29a91b"
        inspector = inspect(db.engine)
        for table in ("transactions", "budgets"):
            assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
            assert {key["referred_table"] for key in inspector.get_foreign_keys(table)} == {"users", "categories"}
        if db.engine.dialect.name == "sqlite":
            assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        if db.engine.dialect.name != "sqlite":
            client = app.test_client()
            if db.engine.dialect.name == "postgresql":
                # Explicit fixture IDs do not advance PostgreSQL's sequences.
                for table in ("users", "categories", "transactions", "budgets"):
                    db.session.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), 1)"))
                db.session.commit()
            registered = client.post("/api/auth/register", json={
                "email": "mysql-check@example.com", "name": "Integration User", "password": "test password",
            })
            assert registered.status_code == 201
            headers = {"Authorization": f"Bearer {registered.json['access_token']}"}
            food = next(row for row in client.get("/api/categories", headers=headers).json if row["name"] == "Food")
            transaction = client.post("/api/transactions", headers=headers, json={
                "category_id": food["id"], "type": "expense", "amount": "25.50", "transaction_date": "2026-01-15",
            })
            assert transaction.status_code == 201
            answer = client.post("/api/chat/message", headers=headers, json={
                "question": "In which areas did I spend my money in January 2026?",
            }).json
            assert answer["display"]["rows"][0]["amount"] == "25.50"
            assert answer["display"]["summary"]["count"] == 1


def test_production_config_rejects_unusable_settings():
    valid = {
        "SECRET_KEY": "test-a" * 8, "JWT_SECRET_KEY": "test-b" * 8,
        "SQLALCHEMY_DATABASE_URI": "postgresql+psycopg://example.invalid/smartspend",
        "AUTO_CREATE_TABLES": False, "RATELIMIT_STORAGE_URI": "redis://example.invalid",
        "CORS_ORIGINS": ["https://example.com"],
    }
    validate_production(valid)
    for key, value in {
        "SECRET_KEY": "", "JWT_SECRET_KEY": valid["SECRET_KEY"], "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "AUTO_CREATE_TABLES": True, "RATELIMIT_STORAGE_URI": "memory://", "CORS_ORIGINS": ["*"],
    }.items():
        with pytest.raises(RuntimeError):
            validate_production({**valid, key: value})


def test_readiness_cors_and_input_validation(monkeypatch):
    app = create_app(TestConfig)
    app.config["MAX_CONTENT_LENGTH"] = 32768
    client = app.test_client()
    assert client.get("/api/ready").json == {"status": "ready"}
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise SQLAlchemyError("database test fixture")
        patch.setattr(db.session, "execute", fail)
        result = client.get("/api/ready")
        assert result.status_code == 503 and result.json == {"status": "unavailable"}
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert allowed.headers["Cache-Control"] == "no-store"
    denied = client.get("/api/health", headers={"Origin": "https://other.example"})
    assert "Access-Control-Allow-Origin" not in denied.headers
    assert client.post("/api/auth/login", json=["invalid"]).status_code == 400
    assert client.post("/api/auth/login", json={"email": "x" * 32768}).status_code == 413


def test_authentication_rejects_expired_tokens_and_rate_limits():
    app = create_app(TestConfig)
    client = app.test_client()
    with app.app_context():
        expired = create_access_token(identity="1", expires_delta=timedelta(seconds=-1))
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert "expired" in response.json["error"]
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": "missing@example.com", "password": "test password"}).status_code == 401
    limited = client.post("/api/auth/login", json={"email": "missing@example.com", "password": "test password"})
    assert limited.status_code == 429 and "Too many requests" in limited.json["error"]


def test_repeated_login_and_logout_revoke_only_the_selected_token():
    app = create_app(TestConfig)
    client = app.test_client()
    credentials = {"email": "session@example.com", "password": "a test password"}
    registration = client.post("/api/auth/register", json={**credentials, "name": "Session Test"})
    assert registration.status_code == 201
    independent = {"Authorization": f"Bearer {registration.json['access_token']}"}
    for _ in range(5):
        login = client.post("/api/auth/login", json=credentials)
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json['access_token']}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.post("/api/auth/logout", headers=headers, json={}).status_code == 204
        assert client.post("/api/auth/logout", headers=headers, json={}).status_code == 204
        revoked = client.get("/api/dashboard", headers=headers)
        assert revoked.status_code == 401 and revoked.json["code"] == "invalid_session"
        assert client.get("/api/auth/me", headers=independent).status_code == 200


def test_authenticated_finance_and_export_lifecycle():
    app = create_app(TestConfig)
    client = app.test_client()

    def account(email):
        response = client.post("/api/auth/register", json={
            "email": email, "name": "Test User", "password": "a test password",
        })
        assert response.status_code == 201
        return response.json["user"]["id"], {"Authorization": f"Bearer {response.json['access_token']}"}

    uid, owner = account("owner@example.com")
    _, other = account("other@example.com")
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.password_hash != "a test password" and user.check_password("a test password")
    assert client.get("/api/auth/me", headers=owner).json["user"]["id"] == uid
    assert client.post("/api/auth/login", json={"email": "owner@example.com", "password": 42}).status_code == 401
    categories = {row["name"]: row["id"] for row in client.get("/api/categories", headers=owner).json}
    food, salary = categories["Food"], categories["Salary"]
    result = client.post("/api/transactions", headers=owner, json={
        "type": "expense", "amount": "15.25", "category_id": food,
        "transaction_date": "2026-09-30", "description": "+ Lunch",
    })
    assert result.status_code == 201
    expense = result.json["id"]
    assert client.post("/api/transactions", headers=owner, json={
        "type": "income", "amount": "100.00", "category_id": salary, "transaction_date": "2026-09-01",
    }).status_code == 201
    assert client.put(f"/api/transactions/{expense}", headers=other, json={"amount": "22.50"}).status_code == 404
    assert client.delete(f"/api/transactions/{expense}", headers=other).status_code == 404
    assert client.put(f"/api/transactions/{expense}", headers=owner, json={"amount": "22.50"}).status_code == 200
    assert client.get("/api/transactions?from=2026-09-30&to=2026-09-30", headers=owner).json["total"] == 1
    assert client.get("/api/transactions?from=2026-10-01&to=2026-09-30", headers=owner).status_code == 400
    assert client.get("/api/transactions", headers=other).json["total"] == 0
    dashboard = client.get("/api/dashboard?year=2026&month=9", headers=owner).json
    assert dashboard["categories"] == [{"name": "Food", "amount": 22.5}]
    assert dashboard["trend"] == [{"month": "Sep", "income": 100.0, "expenses": 22.5}]
    assert dashboard["transaction_count"] == 2
    assert (dashboard["income"], dashboard["expenses"], dashboard["balance"], dashboard["savings_rate"]) == (100, 22.5, 77.5, 77.5)
    assert client.get("/api/dashboard?year=2026&month=all", headers=owner).json["trend"][8] == dashboard["trend"][0]
    empty = client.get("/api/dashboard?year=2026&month=11", headers=owner).json
    assert [item["month"] for item in empty["months"]] == [
        "January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December",
    ]
    assert empty["months"][8] == {"month": "September", "income": 100.0, "expenses": 22.5}
    assert empty["months"][10] == {"month": "November", "income": 0, "expenses": 0}
    assert [empty[key] for key in ("income", "expenses", "balance", "savings_rate", "transaction_count")] == [0] * 5
    assert empty["trend"] == [{"month": "Nov", "income": 0, "expenses": 0}]
    assert empty["categories"] == [] and empty["recent"] == []
    for day, amount in (("2025-11-30", "34.50"), ("2026-11-01", "20.15"), ("2026-12-01", "300")):
        response = client.post("/api/transactions", headers=owner, json={
            "type": "expense", "amount": amount, "category_id": food, "transaction_date": day,
        })
        assert response.status_code == 201
    november = client.get("/api/dashboard?year=2026&month=11", headers=owner).json
    assert [november[key] for key in ("income", "expenses", "balance", "savings_rate", "transaction_count")] == [0, 20.15, -20.15, 0, 1]
    assert november["trend"] == [{"month": "Nov", "income": 0, "expenses": 20.15}]
    assert [row["transaction_date"] for row in november["recent"]] == ["2026-11-01"]
    prior_year = client.get("/api/dashboard?year=2025&month=11", headers=owner).json
    assert prior_year["expenses"] == prior_year["months"][10]["expenses"] == 34.50
    assert prior_year["months"][8]["income"] == 0
    isolated = client.get("/api/dashboard?year=2026&month=11", headers=other).json
    assert all(row["income"] == row["expenses"] == 0 for row in isolated["months"])
    updated_september = client.get("/api/dashboard?year=2026&month=9", headers=owner).json
    assert updated_september.pop("months")[10]["expenses"] == 20.15
    assert updated_september == {key: value for key, value in dashboard.items() if key != "months"}
    answer = client.post("/api/chat/message", headers=owner, json={"question": "How much did I spend in November 2026?"})
    assert "20.15" in answer.json["answer"]
    assert client.get("/api/reports?year=2026&month=9", headers=owner).json["expenses"] == 22.5
    budget = client.post("/api/budgets", headers=owner, json={
        "category_id": food, "amount": "30", "month": 9, "year": 2026,
    })
    assert budget.status_code == 201 and budget.json["remaining"] == 7.5
    november_budget = client.post("/api/budgets", headers=owner, json={
        "category_id": food, "amount": "30", "month": 11, "year": 2026,
    })
    assert november_budget.status_code == 201 and november_budget.json["spent"] == 20.15
    assert client.delete(f"/api/budgets/{budget.json['id']}", headers=other).status_code == 404
    assert client.delete(f"/api/budgets/{budget.json['id']}", headers=owner).status_code == 200
    assert client.get("/api/budgets?year=9999&month=12", headers=owner).status_code == 400
    export = client.get("/api/reports/export", headers=owner)
    exported = list(csv.DictReader(io.StringIO(export.get_data(as_text=True))))
    assert next(row["Description"] for row in exported if row["Date"] == "2026-09-30") == "'+ Lunch"
    assert client.delete(f"/api/transactions/{expense}", headers=owner).status_code == 200
    assert client.get("/api/dashboard?year=2026&month=9", headers=owner).json["expenses"] == 0
