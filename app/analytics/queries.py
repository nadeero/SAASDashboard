"""
app/analytics/queries.py

Raw SQL analytics queries, executed via SQLAlchemy's text() construct and
loaded into pandas DataFrames for further computation/shaping.

DESIGN DECISION: We write these as explicit SQL (via sqlalchemy.text) rather
than building them through the ORM's query API. For genuinely analytical
work -- multi-table joins, GROUP BY, window functions -- hand-written SQL
is both more readable and lets us use database-specific optimizations
later (e.g. Postgres window functions) without fighting the ORM. The ORM
(app/models.py) remains the source of truth for the transactional schema;
this module is the OLAP-style read layer on top of it.

DESIGN DECISION: Every query is parameterized (bound parameters via
SQLAlchemy, never Python string formatting) to eliminate SQL injection risk
even though this is an internal analytics tool -- it's the habit that
matters for portfolio code.

All functions take a SQLAlchemy Engine/Connection and return a pandas
DataFrame, which keeps this module framework-agnostic (works identically
whether called from Flask, a Jupyter notebook, or a script).
"""

import pandas as pd
from sqlalchemy import text


def _read_sql(sql: str, conn, params: dict = None) -> pd.DataFrame:
    return pd.read_sql_query(text(sql), conn, params=params or {})


def monthly_revenue(conn) -> pd.DataFrame:
    """
    Closed-Won bookings by close month. This is the base series that MRR,
    ARR, and revenue-growth KPIs are all derived from.
    """
    sql = """
        SELECT
            strftime('%Y-%m', close_date) AS month,
            COUNT(*) AS deals_won,
            SUM(deal_value) AS bookings
        FROM opportunities
        WHERE stage = 'Closed Won' AND close_date IS NOT NULL
        GROUP BY month
        ORDER BY month
    """
    return _read_sql(sql, conn)


def pipeline_by_stage(conn) -> pd.DataFrame:
    """Current open pipeline value and count, grouped by funnel stage."""
    sql = """
        SELECT
            stage,
            COUNT(*) AS opportunity_count,
            SUM(deal_value) AS total_value,
            AVG(deal_value) AS avg_deal_value
        FROM opportunities
        WHERE stage NOT IN ('Closed Won', 'Closed Lost')
        GROUP BY stage
    """
    return _read_sql(sql, conn)


def funnel_conversion(conn) -> pd.DataFrame:
    """
    All-time counts of opportunities that have ever reached (or passed
    through) each stage, approximated here via current stage plus closed
    outcomes -- i.e. a snapshot funnel. Used to compute stage-to-stage
    conversion rates.
    """
    sql = """
        SELECT stage, COUNT(*) AS opportunity_count, SUM(deal_value) AS total_value
        FROM opportunities
        GROUP BY stage
    """
    return _read_sql(sql, conn)


def win_rate_by_segment(conn) -> pd.DataFrame:
    """Win rate and average deal size, broken out by account company_size."""
    sql = """
        SELECT
            a.company_size,
            SUM(CASE WHEN o.stage = 'Closed Won' THEN 1 ELSE 0 END) AS won,
            SUM(CASE WHEN o.stage = 'Closed Lost' THEN 1 ELSE 0 END) AS lost,
            AVG(CASE WHEN o.stage = 'Closed Won' THEN o.deal_value END) AS avg_won_deal_value
        FROM opportunities o
        JOIN accounts a ON a.account_id = o.account_id
        WHERE o.stage IN ('Closed Won', 'Closed Lost')
        GROUP BY a.company_size
    """
    return _read_sql(sql, conn)


def rep_leaderboard(conn) -> pd.DataFrame:
    """
    Per-rep performance: deals won/lost, win rate, total revenue closed,
    average deal size, and activity volume. This is the core query behind
    the "Sales Rep Performance" dashboard panel.

    IMPLEMENTATION NOTE: opportunities and activities are aggregated in
    separate subqueries rather than joined directly in one query. Joining
    sales_reps -> opportunities -> activities in a single query creates a
    fan-out (each opportunity row is duplicated once per activity against
    it), which silently multiplies SUM(deal_value) by the activity count.
    Aggregating each child table independently before joining back to
    sales_reps avoids this classic SQL correctness bug.
    """
    sql = """
        SELECT
            r.rep_id,
            r.first_name || ' ' || r.last_name AS rep_name,
            r.region,
            COALESCE(opp_stats.deals_won, 0) AS deals_won,
            COALESCE(opp_stats.deals_lost, 0) AS deals_lost,
            COALESCE(opp_stats.deals_open, 0) AS deals_open,
            COALESCE(opp_stats.revenue_closed, 0) AS revenue_closed,
            COALESCE(opp_stats.open_pipeline_value, 0) AS open_pipeline_value,
            COALESCE(act_stats.total_activities, 0) AS total_activities
        FROM sales_reps r
        LEFT JOIN (
            SELECT
                rep_id,
                SUM(CASE WHEN stage = 'Closed Won' THEN 1 ELSE 0 END) AS deals_won,
                SUM(CASE WHEN stage = 'Closed Lost' THEN 1 ELSE 0 END) AS deals_lost,
                SUM(CASE WHEN stage NOT IN ('Closed Won','Closed Lost') THEN 1 ELSE 0 END) AS deals_open,
                SUM(CASE WHEN stage = 'Closed Won' THEN deal_value ELSE 0 END) AS revenue_closed,
                SUM(CASE WHEN stage NOT IN ('Closed Won','Closed Lost') THEN deal_value ELSE 0 END) AS open_pipeline_value
            FROM opportunities
            GROUP BY rep_id
        ) opp_stats ON opp_stats.rep_id = r.rep_id
        LEFT JOIN (
            SELECT rep_id, COUNT(*) AS total_activities
            FROM activities
            GROUP BY rep_id
        ) act_stats ON act_stats.rep_id = r.rep_id
        ORDER BY revenue_closed DESC
    """
    return _read_sql(sql, conn)


def customer_segmentation(conn) -> pd.DataFrame:
    """Account counts, total closed revenue, and avg deal value by industry x size."""
    sql = """
        SELECT
            a.industry,
            a.company_size,
            COUNT(DISTINCT a.account_id) AS account_count,
            COALESCE(SUM(CASE WHEN o.stage = 'Closed Won' THEN o.deal_value END), 0) AS total_revenue,
            COALESCE(AVG(CASE WHEN o.stage = 'Closed Won' THEN o.deal_value END), 0) AS avg_deal_value
        FROM accounts a
        LEFT JOIN opportunities o ON o.account_id = a.account_id
        GROUP BY a.industry, a.company_size
    """
    return _read_sql(sql, conn)


def account_revenue_detail(conn) -> pd.DataFrame:
    """
    Per-account rollup: total won revenue, opportunity count, last activity
    date. Opportunities and activities are aggregated in separate
    subqueries before joining back to accounts, for the same fan-out
    reason documented in rep_leaderboard() above.
    """
    sql = """
        SELECT
            a.account_id,
            a.company_name,
            a.industry,
            a.company_size,
            a.created_date,
            COALESCE(opp_stats.opportunity_count, 0) AS opportunity_count,
            COALESCE(opp_stats.total_won_revenue, 0) AS total_won_revenue,
            act_stats.last_activity_date AS last_activity_date
        FROM accounts a
        LEFT JOIN (
            SELECT
                account_id,
                COUNT(*) AS opportunity_count,
                SUM(CASE WHEN stage = 'Closed Won' THEN deal_value ELSE 0 END) AS total_won_revenue
            FROM opportunities
            GROUP BY account_id
        ) opp_stats ON opp_stats.account_id = a.account_id
        LEFT JOIN (
            SELECT o.account_id, MAX(act.activity_date) AS last_activity_date
            FROM activities act
            JOIN opportunities o ON o.opportunity_id = act.opportunity_id
            GROUP BY o.account_id
        ) act_stats ON act_stats.account_id = a.account_id
    """
    return _read_sql(sql, conn)


def activity_volume_by_type(conn) -> pd.DataFrame:
    sql = """
        SELECT activity_type, COUNT(*) AS activity_count
        FROM activities
        GROUP BY activity_type
        ORDER BY activity_count DESC
    """
    return _read_sql(sql, conn)


def all_opportunities_raw(conn) -> pd.DataFrame:
    """Full opportunity fact table joined with account attributes, used as the
    base DataFrame for pandas-side KPI calculations (forecasting, CLV, churn)."""
    sql = """
        SELECT
            o.opportunity_id, o.account_id, o.rep_id, o.opportunity_name,
            o.stage, o.deal_value, o.created_date, o.close_date,
            a.company_name, a.industry, a.company_size, a.created_date AS account_created_date
        FROM opportunities o
        JOIN accounts a ON a.account_id = o.account_id
    """
    return _read_sql(sql, conn)
