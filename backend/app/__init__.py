from hmac import compare_digest
from urllib.parse import urlsplit

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import make_url
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address, default_limits=["300 per hour"])


def validate_production(config):
    for key in ("SECRET_KEY", "JWT_SECRET_KEY"):
        value = config.get(key) or ""
        if len(value) < 32 or value.startswith("replace-with"):
            raise RuntimeError(f"{key} must contain an independent random secret of at least 32 characters.")
    if config["SECRET_KEY"] == config["JWT_SECRET_KEY"]:
        raise RuntimeError("Use different secrets for SECRET_KEY and JWT_SECRET_KEY.")
    if make_url(config["SQLALCHEMY_DATABASE_URI"]).get_backend_name() not in {"mysql", "postgresql"}:
        raise RuntimeError("Set DATABASE_URL to the existing MySQL or PostgreSQL database.")
    if config["AUTO_CREATE_TABLES"]:
        raise RuntimeError("Disable AUTO_CREATE_TABLES and run the migration before startup.")
    if not config["RATELIMIT_STORAGE_URI"].startswith(("redis://", "rediss://")):
        raise RuntimeError("Configure a shared Redis-compatible RATELIMIT_STORAGE_URI.")
    origins = config["CORS_ORIGINS"]
    if not origins or any(
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.path
        or parsed.query or parsed.fragment or "*" in origin
        or parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        for origin in origins for parsed in [urlsplit(origin)]
    ):
        raise RuntimeError("Configure explicit HTTPS FRONTEND_ORIGIN values.")


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    if app.config.get("PRODUCTION"):
        validate_production(app.config)
    if app.config.get("TRUSTED_PROXY_HOPS", 0) > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config["TRUSTED_PROXY_HOPS"])
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    limiter.init_app(app)
    CORS(app, resources={r"/api/.*": {"origins": app.config["CORS_ORIGINS"]}})

    from app import models  # Register model metadata for SQLAlchemy and Flask-Migrate.
    from app.api import api
    app.register_blueprint(api)

    if app.config.get("AUTO_CREATE_TABLES", True):
        with app.app_context():
            db.create_all()

    @app.get("/api/health")
    @limiter.exempt
    def health():
        return jsonify({"status": "ok", "service": "smartspend-api"}), 200

    @app.get("/api/ready")
    @limiter.exempt
    def readiness():
        try:
            db.session.execute(text("SELECT 1"))
            db.session.execute(db.select(models.User.id, models.User.updated_at).limit(1))
            db.session.execute(db.select(models.RevokedAccessToken.jti).limit(1))
            if app.config.get("PRODUCTION") and not limiter.storage.check():
                return jsonify({"status": "unavailable"}), 503
        except SQLAlchemyError:
            db.session.rollback()
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ready"}), 200

    @app.errorhandler(413)
    def request_too_large(_error):
        return jsonify({"error": "Request is too large."}), 413

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        response = error.get_response()
        response.set_data(app.json.dumps({"error": "Too many requests. Please try again shortly."}))
        response.mimetype = "application/json"
        return response

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error("SmartSpend database request failed (%s)", type(error).__name__)
        return jsonify({"error": "The database is temporarily unavailable."}), 503

    @app.after_request
    def protect_api_responses(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @jwt.token_in_blocklist_loader
    def stale_account_token(_header, payload):
        marker = payload.get("pv")
        if not isinstance(marker, str) or not str(payload.get("sub", "")).isdigit():
            return True
        user = db.session.get(models.User, int(payload["sub"]))
        return (
            not user or not compare_digest(marker, user.password_marker(app.config["JWT_SECRET_KEY"]))
            or db.session.get(models.RevokedAccessToken, payload["jti"]) is not None
        )

    @jwt.revoked_token_loader
    def revoked_token(_header, _payload):
        return jsonify({"error": "Your session has ended. Please sign in again.", "code": "invalid_session"}), 401

    @jwt.unauthorized_loader
    def missing_token(_reason):
        return jsonify({"error": "Sign in to continue.", "code": "invalid_session"}), 401

    @jwt.invalid_token_loader
    def invalid_token(_reason):
        return jsonify({"error": "Your session is invalid. Please sign in again.", "code": "invalid_session"}), 401

    @jwt.expired_token_loader
    def expired_token(_header, _payload):
        return jsonify({"error": "Your session expired. Please sign in again.", "code": "invalid_session"}), 401

    return app
