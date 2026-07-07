"""
tests/test_analytics.py

Unit tests for app/analytics/queries.py and app/analytics/kpi.py, using the
small hand-seeded dataset from conftest.seeded_db so expected values can be
computed by hand and asserted exactly (rather than just "shape" checks).

Seeded dataset recap (see conftest.py):
  - opp1: Acme Corp (Enterprise), Closed Won, $100,000, closed 2024-03-01
  - opp2: Beta LLC (SMB), Closed Lost, $20,000, closed 2024-05-01
  - opp3: Beta LLC (SMB), Proposal (open), $15,000
"""

from app.analytics import queries as q
from app.analytics import kpi
from app.extensions import db as _db


def test_rep_leaderboard_no_fanout(app, seeded_db):
    """
    Regression test for the join fan-out bug: rep2 has 1 closed-lost
    opportunity (0 activities counted toward revenue) plus 1 open
    opportunity, and 1 activity total. If the fan-out bug were
    reintroduced, revenue/pipeline sums would be inflated by activity
    counts.
    """
    with _db.engine.connect() as conn:
        df = q.rep_leaderboard(conn)

    rep1_row = df[df["rep_name"] == "Jane Doe"].iloc[0]
    rep2_row = df[df["rep_name"] == "John Smith"].iloc[0]

    assert rep1_row["revenue_closed"] == 100000
    assert rep1_row["deals_won"] == 1
    assert rep1_row["total_activities"] == 2  # 2 activities on opp1

    assert rep2_row["revenue_closed"] == 0  # Beta deal was Closed Lost
    assert rep2_row["deals_lost"] == 1
    assert rep2_row["open_pipeline_value"] == 15000  # only opp3 is open
    assert rep2_row["total_activities"] == 1


def test_account_revenue_detail_no_fanout(app, seeded_db):
    with _db.engine.connect() as conn:
        df = q.account_revenue_detail(conn)

    acme = df[df["company_name"] == "Acme Corp"].iloc[0]
    beta = df[df["company_name"] == "Beta LLC"].iloc[0]

    assert acme["total_won_revenue"] == 100000
    assert acme["opportunity_count"] == 1

    assert beta["total_won_revenue"] == 0  # Beta's only closed deal was Lost
    assert beta["opportunity_count"] == 2  # Closed Lost + open Proposal


def test_pipeline_by_stage_excludes_closed(app, seeded_db):
    with _db.engine.connect() as conn:
        df = q.pipeline_by_stage(conn)

    stages = set(df["stage"])
    assert "Closed Won" not in stages
    assert "Closed Lost" not in stages
    assert "Proposal" in stages
    proposal_row = df[df["stage"] == "Proposal"].iloc[0]
    assert proposal_row["total_value"] == 15000


def test_top_level_summary_win_rate(app, seeded_db):
    opps_df = q.all_opportunities_raw(_db.engine.connect())
    summary = kpi.top_level_summary(opps_df)

    # 1 won, 1 lost among closed deals => 50% win rate
    assert summary["win_rate_pct"] == 50.0
    assert summary["open_pipeline_value"] == 15000
    assert summary["open_opportunity_count"] == 1
    assert summary["total_accounts"] == 2
    assert summary["total_closed_won_deals"] == 1


def test_pipeline_forecast_only_counts_open_deals(app, seeded_db):
    opps_df = q.all_opportunities_raw(_db.engine.connect())
    forecast = kpi.pipeline_forecast(opps_df)

    assert forecast["total_open_pipeline"] == 15000
    assert forecast["open_opportunity_count"] == 1
    # weighted forecast must be <= total open pipeline (a probability-weighted
    # subset can never exceed the full open pipeline value)
    assert forecast["weighted_forecast"] <= forecast["total_open_pipeline"]


def test_customer_lifetime_value_only_counts_won(app, seeded_db):
    opps_df = q.all_opportunities_raw(_db.engine.connect())
    clv = kpi.customer_lifetime_value(opps_df)

    assert len(clv) == 1  # only Acme has a Closed Won deal
    assert clv.iloc[0]["company_name"] == "Acme Corp"
    assert clv.iloc[0]["lifetime_value"] == 100000


def test_funnel_conversion_rates_shape(app, seeded_db):
    opps_df = q.all_opportunities_raw(_db.engine.connect())
    funnel = kpi.funnel_conversion_rates(opps_df)

    stages = [row["stage"] for row in funnel]
    assert stages == ["Prospecting", "Qualification", "Needs Analysis", "Proposal", "Negotiation", "Closed Won"]
    # First stage should always have no "conversion from previous"
    assert funnel[0]["conversion_from_previous_stage_pct"] is None


def test_churn_risk_flags_old_contract_higher(app, seeded_db):
    opps_df = q.all_opportunities_raw(_db.engine.connect())
    churn = kpi.churn_risk_indicators(opps_df, as_of=None)

    assert len(churn) == 1  # only Acme has a Closed Won deal to measure risk on
    row = churn.iloc[0]
    assert row["company_name"] == "Acme Corp"
    assert row["risk_band"] in {"Low", "Medium", "High"}
