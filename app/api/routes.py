"""
app/api/routes.py

REST API surface for the Revenue Intelligence Platform.

DESIGN DECISION: Analytics endpoints (/api/kpis/*) are the primary surface
this project is built around -- they return pre-shaped JSON the dashboard
consumes directly. We also expose thin CRUD-style read endpoints for the
underlying entities (/api/accounts, /api/opportunities, etc.) with
pagination and filtering, since a real RevOps tool needs both the
aggregate view and the ability to drill into individual records.

DESIGN DECISION: All analytics endpoints open a raw SQLAlchemy connection
(db.engine.connect()) and hand it to the analytics/queries.py + kpi.py
functions, rather than re-implementing the SQL inline in the route
handlers. This keeps the analytics logic testable independent of Flask
(see tests/test_analytics.py) and keeps route handlers thin: fetch data,
shape response, return JSON.

DESIGN DECISION: Every list endpoint supports `page` and `per_page` query
params with server-side enforced maximums (see config.MAX_PAGE_SIZE) to
prevent accidentally returning the entire table in one response as the
dataset grows.
"""

from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import select, func

from app.extensions import db
from app.models import SalesRep, Account, Contact, Opportunity, Activity
from app.analytics import queries as q
from app.analytics import kpi

api_bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paginate_args():
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = request.args.get("per_page", current_app.config["DEFAULT_PAGE_SIZE"], type=int)
    per_page = min(max(per_page, 1), current_app.config["MAX_PAGE_SIZE"])
    return page, per_page


def _paginated_response(query, page, per_page, serialize):
    total = db.session.scalar(select(func.count()).select_from(query.subquery()))
    items = db.session.execute(query.limit(per_page).offset((page - 1) * per_page)).scalars().all()
    return {
        "items": [serialize(item) for item in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page if total else 0,
    }


def _opps_df():
    with db.engine.connect() as conn:
        return q.all_opportunities_raw(conn)


# ---------------------------------------------------------------------------
# Entity endpoints (paginated, filterable reads)
# ---------------------------------------------------------------------------

@api_bp.get("/sales-reps")
def list_sales_reps():
    page, per_page = _paginate_args()
    region = request.args.get("region")
    stmt = select(SalesRep)
    if region:
        stmt = stmt.where(SalesRep.region == region)
    return jsonify(_paginated_response(stmt, page, per_page, lambda r: r.to_dict()))


@api_bp.get("/accounts")
def list_accounts():
    page, per_page = _paginate_args()
    industry = request.args.get("industry")
    company_size = request.args.get("company_size")
    stmt = select(Account)
    if industry:
        stmt = stmt.where(Account.industry == industry)
    if company_size:
        stmt = stmt.where(Account.company_size == company_size)
    return jsonify(_paginated_response(stmt, page, per_page, lambda a: a.to_dict()))


@api_bp.get("/accounts/<int:account_id>")
def get_account(account_id):
    account = db.session.get(Account, account_id)
    if not account:
        return jsonify({"error": "Account not found"}), 404
    data = account.to_dict()
    data["contacts"] = [c.to_dict() for c in account.contacts]
    data["opportunities"] = [o.to_dict() for o in account.opportunities]
    return jsonify(data)


@api_bp.get("/contacts")
def list_contacts():
    page, per_page = _paginate_args()
    account_id = request.args.get("account_id", type=int)
    stmt = select(Contact)
    if account_id:
        stmt = stmt.where(Contact.account_id == account_id)
    return jsonify(_paginated_response(stmt, page, per_page, lambda c: c.to_dict()))


@api_bp.get("/opportunities")
def list_opportunities():
    page, per_page = _paginate_args()
    stage = request.args.get("stage")
    rep_id = request.args.get("rep_id", type=int)
    stmt = select(Opportunity)
    if stage:
        stmt = stmt.where(Opportunity.stage == stage)
    if rep_id:
        stmt = stmt.where(Opportunity.rep_id == rep_id)
    return jsonify(_paginated_response(stmt, page, per_page, lambda o: o.to_dict()))


@api_bp.get("/activities")
def list_activities():
    page, per_page = _paginate_args()
    opportunity_id = request.args.get("opportunity_id", type=int)
    stmt = select(Activity)
    if opportunity_id:
        stmt = stmt.where(Activity.opportunity_id == opportunity_id)
    return jsonify(_paginated_response(stmt, page, per_page, lambda act: act.to_dict()))


# ---------------------------------------------------------------------------
# Analytics / KPI endpoints -- the core of the dashboard
# ---------------------------------------------------------------------------

@api_bp.get("/kpis/summary")
def kpi_summary():
    """Top-line KPI cards: ARR, MRR, growth, win rate, open pipeline."""
    return jsonify(kpi.top_level_summary(_opps_df()))


@api_bp.get("/kpis/revenue-timeseries")
def kpi_revenue_timeseries():
    """MRR/ARR + growth rates, month by month -- powers the revenue chart."""
    mrr_df = kpi.build_mrr_timeseries(_opps_df())
    growth_df = kpi.revenue_growth(mrr_df)
    return jsonify(growth_df.fillna(0).to_dict(orient="records"))


@api_bp.get("/kpis/pipeline")
def kpi_pipeline():
    """Open pipeline breakdown by stage, plus a stage-weighted forecast."""
    with db.engine.connect() as conn:
        by_stage = q.pipeline_by_stage(conn)
    forecast = kpi.pipeline_forecast(_opps_df())
    return jsonify({
        "by_stage": by_stage.to_dict(orient="records"),
        "forecast": forecast,
    })


@api_bp.get("/kpis/funnel")
def kpi_funnel():
    """Sales funnel conversion rates, stage by stage."""
    return jsonify(kpi.funnel_conversion_rates(_opps_df()))


@api_bp.get("/kpis/rep-leaderboard")
def kpi_rep_leaderboard():
    with db.engine.connect() as conn:
        df = q.rep_leaderboard(conn)
    return jsonify(df.to_dict(orient="records"))


@api_bp.get("/kpis/segmentation")
def kpi_segmentation():
    with db.engine.connect() as conn:
        df = q.customer_segmentation(conn)
    return jsonify(df.to_dict(orient="records"))


@api_bp.get("/kpis/clv")
def kpi_clv():
    """Customer lifetime value, top N accounts by realized revenue."""
    limit = request.args.get("limit", 20, type=int)
    df = kpi.customer_lifetime_value(_opps_df())
    return jsonify(df.head(limit).to_dict(orient="records"))


@api_bp.get("/kpis/churn-risk")
def kpi_churn_risk():
    """Accounts flagged by churn-risk score, highest risk first."""
    band = request.args.get("band")  # optional filter: High/Medium/Low
    df = kpi.churn_risk_indicators(_opps_df())
    if band:
        df = df[df["risk_band"] == band]
    df = df.copy()
    df["last_close_date"] = df["last_close_date"].astype(str)
    return jsonify(df.to_dict(orient="records"))


@api_bp.get("/kpis/activity-volume")
def kpi_activity_volume():
    with db.engine.connect() as conn:
        df = q.activity_volume_by_type(conn)
    return jsonify(df.to_dict(orient="records"))
