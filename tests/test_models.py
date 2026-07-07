"""
tests/test_models.py

Unit tests for the ORM layer: field defaults, relationships, cascade
behavior, and validation logic (e.g. invalid stage rejection).
"""

import pytest
from datetime import date
from app.models import SalesRep, Account, Contact, Opportunity, Activity


def test_sales_rep_full_name(seeded_db):
    rep = seeded_db["reps"][0]
    assert rep.full_name == "Jane Doe"


def test_account_to_dict_shape(seeded_db):
    acc = seeded_db["accounts"][0]
    d = acc.to_dict()
    assert d["company_name"] == "Acme Corp"
    assert d["company_size"] == "Enterprise"
    assert "account_id" in d


def test_opportunity_is_closed_and_is_won(seeded_db):
    won, lost, open_ = seeded_db["opportunities"]
    assert won.is_closed is True
    assert won.is_won is True
    assert lost.is_closed is True
    assert lost.is_won is False
    assert open_.is_closed is False
    assert open_.is_won is False


def test_opportunity_rejects_invalid_stage(app, db):
    with pytest.raises(ValueError):
        Opportunity(
            opportunity_name="Bad Opp",
            stage="Not A Real Stage",
            deal_value=1000,
            created_date=date(2024, 1, 1),
        )


def test_account_cascade_delete_removes_contacts_and_opportunities(app, db, seeded_db):
    acc2 = seeded_db["accounts"][1]  # has 1 contact, 2 opportunities
    account_id = acc2.account_id

    db.session.delete(acc2)
    db.session.commit()

    remaining_contacts = db.session.query(Contact).filter_by(account_id=account_id).count()
    remaining_opps = db.session.query(Opportunity).filter_by(account_id=account_id).count()
    assert remaining_contacts == 0
    assert remaining_opps == 0


def test_opportunity_cascade_delete_removes_activities(app, db, seeded_db):
    opp1 = seeded_db["opportunities"][0]
    opp_id = opp1.opportunity_id

    db.session.delete(opp1)
    db.session.commit()

    remaining = db.session.query(Activity).filter_by(opportunity_id=opp_id).count()
    assert remaining == 0


def test_relationships_navigable_both_directions(seeded_db):
    acc1 = seeded_db["accounts"][0]
    assert len(acc1.opportunities) == 1
    assert acc1.opportunities[0].account is acc1

    rep1 = seeded_db["reps"][0]
    assert len(rep1.opportunities) == 1
