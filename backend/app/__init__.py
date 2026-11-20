from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address, default_limits=["300 per hour"])


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    limiter.init_app(app)
    CORS(app, origins=app.config["CORS_ORIGINS"])

    from app import models  # Register model metadata for SQLAlchemy and Flask-Migrate.
    from app.api import api
    app.register_blueprint(api)

    if app.config.get("AUTO_CREATE_TABLES", True):
        with app.app_context():
            db.create_all()

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "smartspend-api"}), 200

    @jwt.unauthorized_loader
    def missing_token(_reason):
        return jsonify({"error": "Sign in to continue."}), 401

    @jwt.invalid_token_loader
    def invalid_token(_reason):
        return jsonify({"error": "Your session is invalid. Please sign in again."}), 401

    @jwt.expired_token_loader
    def expired_token(_header, _payload):
        return jsonify({"error": "Your session expired. Please sign in again."}), 401

    return app
