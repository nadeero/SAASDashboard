"""
tests/test_etl.py

Tests for the synthetic data generator (app/etl/generate_data.py). These
check structural / statistical properties of the full-scale generated
dataset (volume thresholds, referential consistency, valid enum values)
rather than exact values, since the dataset is large and probabilistic
by design. Reproducibility is verified via the fixed random seed.
"""

from app.etl.generate_data import generate_full_dataset
from app.models import STAGE_CHOICES, COMPANY_SIZE_CHOICES, ACTIVITY_TYPE_CHOICES


def test_dataset_meets_minimum_volume_requirements():
    data = generate_full_dataset()
    assert len(data["accounts"]) >= 1000
    assert len(data["contacts"]) >= 2000
    assert len(data["opportunities"]) >= 1500
    assert len(data["activities"]) >= 5000
    assert len(data["reps"]) >= 20


def test_dataset_is_reproducible_given_fixed_seed():
    data1 = generate_full_dataset()
    data2 = generate_full_dataset()

    assert len(data1["accounts"]) == len(data2["accounts"])
    assert [a.company_name for a in data1["accounts"]] == [a.company_name for a in data2["accounts"]]
    assert [float(o.deal_value) for o in data1["opportunities"]] == [float(o.deal_value) for o in data2["opportunities"]]


def test_all_opportunity_stages_are_valid():
    data = generate_full_dataset()
    for opp in data["opportunities"]:
        assert opp.stage in STAGE_CHOICES


def test_all_account_sizes_are_valid():
    data = generate_full_dataset()
    for acc in data["accounts"]:
        assert acc.company_size in COMPANY_SIZE_CHOICES


def test_all_activity_types_are_valid():
    data = generate_full_dataset()
    for act in data["activities"]:
        assert act.activity_type in ACTIVITY_TYPE_CHOICES


def test_closed_opportunities_have_close_date_open_do_not():
    data = generate_full_dataset()
    for opp in data["opportunities"]:
        if opp.stage in ("Closed Won", "Closed Lost"):
            assert opp.close_date is not None
        else:
            assert opp.close_date is None


def test_contact_emails_are_unique():
    data = generate_full_dataset()
    emails = [c.email for c in data["contacts"]]
    assert len(emails) == len(set(emails))


def test_enterprise_deals_average_larger_than_smb():
    """Sanity check that the deal-value simulation logic actually produces
    the intended size-correlated deal values (a core realism requirement)."""
    data = generate_full_dataset()
    smb_values = [float(o.deal_value) for o in data["opportunities"] if o.account.company_size == "SMB"]
    ent_values = [float(o.deal_value) for o in data["opportunities"] if o.account.company_size == "Enterprise"]
    assert (sum(ent_values) / len(ent_values)) > (sum(smb_values) / len(smb_values))


def test_deal_values_are_positive():
    data = generate_full_dataset()
    for opp in data["opportunities"]:
        assert float(opp.deal_value) > 0


def test_win_rate_is_within_realistic_bounds():
    data = generate_full_dataset()
    won = sum(1 for o in data["opportunities"] if o.stage == "Closed Won")
    lost = sum(1 for o in data["opportunities"] if o.stage == "Closed Lost")
    closed = won + lost
    assert closed > 0
    win_rate = won / closed
    assert 0.15 < win_rate < 0.65  # sanity band for a realistic B2B SaaS win rate
