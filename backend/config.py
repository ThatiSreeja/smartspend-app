import os
import secrets
from dotenv import load_dotenv

load_dotenv()


class Config:
    PRODUCTION = os.getenv("SMARTSPEND_ENV") == "production" or os.getenv("RENDER") == "true"
    SECRET_KEY = os.getenv("SECRET_KEY") or (None if PRODUCTION else secrets.token_urlsafe(48))
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or (None if PRODUCTION else secrets.token_urlsafe(48))
    database_url = os.getenv("DATABASE_URL") or "sqlite:///smartspend-dev.db"
    if database_url.startswith(("postgres://", "postgresql://")):
        database_url = "postgresql+psycopg://" + database_url.split("://", 1)[1]
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "hide_parameters": True}
    JWT_ACCESS_TOKEN_EXPIRES = 60 * 60
    CORS_ORIGINS = [
        origin.strip().rstrip("/") for origin in os.getenv(
            "FRONTEND_ORIGIN", "" if PRODUCTION else "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",") if origin.strip()
    ]
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM = os.getenv("SMTP_FROM")
    AUTO_CREATE_TABLES = os.getenv("AUTO_CREATE_TABLES", "false" if PRODUCTION else "true").lower() == "true"
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_STORAGE_OPTIONS = {"socket_connect_timeout": 2, "socket_timeout": 2} if (
        RATELIMIT_STORAGE_URI.startswith(("redis://", "rediss://"))
    ) else {}
    TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
    MAX_CONTENT_LENGTH = 32 * 1024
    AI_SHARE_FINANCIAL_SUMMARIES = os.getenv("AI_SHARE_FINANCIAL_SUMMARIES", "false").lower() == "true"

