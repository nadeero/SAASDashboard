"""
app/__init__.py

Flask application factory.

DESIGN DECISION: We use the "application factory" pattern (create_app())
rather than a module-level `app = Flask(__name__)`. This is what allows
tests to spin up isolated app instances with TestingConfig (in-memory DB)
without touching the dev SQLite file, and is the pattern Flask's own docs
recommend for anything beyond a toy script.
"""

from flask import Flask, jsonify
from flask_cors import CORS

from app.extensions import db
from config import get_config


def create_app(env_name: str = None):
    app = Flask(__name__)
    app.config.from_object(get_config(env_name))

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    from app.api.routes import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "revenue-intelligence-api"})

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": "Internal server error"}), 500

    return app
