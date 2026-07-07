"""
config.py

Centralized configuration using the "12-factor app" pattern: settings are
read from environment variables with sensible local defaults, so the same
codebase runs unmodified in dev, test, and production.

DESIGN DECISION: We define a base Config class and environment-specific
subclasses (Development, Testing, Production) rather than scattering
if/else logic through the app. This is the standard Flask pattern and
makes it obvious at a glance what changes between environments.

DESIGN DECISION: SQLALCHEMY_DATABASE_URI defaults to a local SQLite file,
but every other part of the ORM layer (models, queries) is written using
SQLAlchemy Core/ORM constructs that are portable to PostgreSQL. The only
thing that changes to migrate is this URI (e.g.
'postgresql://user:pass@host:5432/revenue_intelligence') plus swapping
the dialect driver in requirements.txt (psycopg2-binary). No query or
model code needs to change.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    # SQLAlchemy
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # Verifies connections before use (important once on Postgres)
    }

    # Pagination defaults used across the API
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 500

    # CORS - allow the static dashboard (served from anywhere in dev) to call the API
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'revenue_intelligence.db'}"
    )


class TestingConfig(Config):
    TESTING = True
    # In-memory DB for fast, isolated test runs. Each test module that needs
    # data creates its own engine/session so tests never collide.
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False
    # In production this MUST be a real Postgres URL supplied via env var.
    # e.g. postgresql://user:password@host:5432/revenue_intelligence
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'revenue_intelligence.db'}"
    )


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(env_name: str = None):
    env_name = env_name or os.environ.get("FLASK_ENV", "development")
    return config_by_name.get(env_name, DevelopmentConfig)
