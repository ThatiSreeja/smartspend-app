from app import create_app
from itsdangerous import URLSafeTimedSerializer


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

    token = URLSafeTimedSerializer(TestConfig.SECRET_KEY).dumps("budget@example.com", salt="smartspend-password-reset")
    reset = client.post("/api/auth/reset-password", json={"token": token, "password": "new password 74"})
    assert reset.status_code == 200
    assert client.post("/api/auth/login", json={"email": "budget@example.com", "password": "new password 74"}).status_code == 200
