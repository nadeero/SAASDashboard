"""
tests/conftest.py

Shared pytest fixtures.

DESIGN DECISION: Each test gets a fresh Flask app configured with
TestingConfig (SQLite in-memory) and a small, deterministic hand-seeded
dataset -- NOT the full synthetic generator. Tests should be fast and
their expected values hand-computable; the full generator is exercised
separately by tests/test_etl.py, which only checks structural properties
(counts, referential integrity) rather than exact values.
"""

import pytest
from datetime import date

from app import create_app
from app.extensions import db as _db
from app.models import SalesRep, Account, Contact, Opportunity, Activity


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def seeded_db(app, db):
    """A small, hand-computable dataset for deterministic assertions."""
    rep1 = SalesRep(first_name="Jane", last_name="Doe", region="West", hire_date=date(2023, 1, 15))
    rep2 = SalesRep(first_name="John", last_name="Smith", region="East", hire_date=date(2022, 6, 1))
    db.session.add_all([rep1, rep2])
    db.session.flush()

    acc1 = Account(company_name="Acme Corp", industry="Technology", company_size="Enterprise",
                    location="San Francisco, CA", created_date=date(2024, 1, 1))
    acc2 = Account(company_name="Beta LLC", industry="Retail & E-commerce", company_size="SMB",
                    location="Austin, TX", created_date=date(2024, 3, 1))
    db.session.add_all([acc1, acc2])
    db.session.flush()

    contact1 = Contact(account=acc1, name="Sam Buyer", job_title="CTO", email="sam@acme.com")
    contact2 = Contact(account=acc2, name="Robin Buyer", job_title="CEO", email="robin@beta.com")
    db.session.add_all([contact1, contact2])
    db.session.flush()

    opp1 = Opportunity(account=acc1, rep=rep1, opportunity_name="Acme - New Business",
                        stage="Closed Won", deal_value=100000, created_date=date(2024, 2, 1),
                        close_date=date(2024, 3, 1))
    opp2 = Opportunity(account=acc2, rep=rep2, opportunity_name="Beta - New Business",
                        stage="Closed Lost", deal_value=20000, created_date=date(2024, 4, 1),
                        close_date=date(2024, 5, 1))
    opp3 = Opportunity(account=acc2, rep=rep2, opportunity_name="Beta - Expansion",
                        stage="Proposal", deal_value=15000, created_date=date(2024, 6, 1),
                        close_date=None)
    db.session.add_all([opp1, opp2, opp3])
    db.session.flush()

    act1 = Activity(opportunity=opp1, rep=rep1, activity_type="Call",
                     activity_date=date(2024, 2, 5), notes="Discovery call")
    act2 = Activity(opportunity=opp1, rep=rep1, activity_type="Demo",
                     activity_date=date(2024, 2, 10), notes="Product demo")
    act3 = Activity(opportunity=opp2, rep=rep2, activity_type="Call",
                     activity_date=date(2024, 4, 5), notes="Discovery call")
    db.session.add_all([act1, act2, act3])
    db.session.commit()

    return {
        "reps": [rep1, rep2],
        "accounts": [acc1, acc2],
        "contacts": [contact1, contact2],
        "opportunities": [opp1, opp2, opp3],
        "activities": [act1, act2, act3],
    }
