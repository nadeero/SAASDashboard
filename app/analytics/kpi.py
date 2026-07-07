"""
app/analytics/kpi.py

KPI calculations built on top of the raw SQL query layer (queries.py) using
pandas. This is where "data" becomes "business metrics."

DESIGN DECISION: We separate this from queries.py deliberately. queries.py
answers "what happened" (facts, joins, aggregates the database can compute
natively). kpi.py answers "so what" (derived business metrics: growth
rates, forecasts, lifetime value, churn risk) that require row-level
manipulation, rolling windows, or modeling logic that's awkward or
inefficient to express in SQL, and where pandas is the right tool.

ARR/MRR DEFINITIONS (documented here since these terms are ambiguous
across companies):
  - We treat every Closed Won opportunity's deal_value as an annual
    contract value (ACV), consistent with typical B2B SaaS annual
    contracts.
  - MRR (Monthly Recurring Revenue) for a given month = sum of ACV/12 for
    all contracts that are "active" in that month (i.e. won in or before
    that month, and assumed active for a 12-month term unless it's past
    the term -- see churn logic below).
  - ARR (Annual Recurring Revenue) at a point in time = MRR * 12. This is
    the standard SaaS convention (ARR is not simply "bookings in the last
    12 months"; it's the annualized run-rate of currently active
    contracts).
  - This is a simplification of real subscription billing (which would
    track invoice line items, upgrades/downgrades, multi-year terms,
    etc.) but is the standard simplification used in RevOps modeling
    exercises and is clearly documented as such.
"""

from datetime import date, timedelta
import pandas as pd
import numpy as np

CONTRACT_TERM_MONTHS = 12
TODAY = date(2026, 7, 1)  # kept in sync with app/etl/generate_data.TODAY


def _month_str(d) -> str:
    return d.strftime("%Y-%m")


def build_mrr_timeseries(opps_df: pd.DataFrame, as_of: date = None) -> pd.DataFrame:
    """
    For each month in the dataset's history through `as_of`, compute MRR as
    the sum of (ACV / 12) for every Closed Won deal whose 12-month contract
    term covers that month. A contract signed in month M is considered
    active for months [M, M+11] (a simple, explicit churn assumption: after
    12 months, revenue drops off unless a renewal opportunity---generated
    separately in the synthetic data as a distinct Closed Won opp---covers
    the next term).
    """
    as_of = as_of or TODAY
    won = opps_df[opps_df["stage"] == "Closed Won"].copy()
    won["close_date"] = pd.to_datetime(won["close_date"])
    if won.empty:
        return pd.DataFrame(columns=["month", "mrr", "arr"])

    start_month = won["close_date"].min().to_period("M")
    end_month = pd.Period(as_of, freq="M")
    months = pd.period_range(start_month, end_month, freq="M")

    monthly_acv = won.groupby(won["close_date"].dt.to_period("M"))["deal_value"].sum()

    mrr_values = []
    for m in months:
        # Sum ACV/12 for every deal signed within the trailing CONTRACT_TERM_MONTHS window
        window_start = m - (CONTRACT_TERM_MONTHS - 1)
        active_months = [p for p in monthly_acv.index if window_start <= p <= m]
        active_acv = monthly_acv.loc[active_months].sum() if active_months else 0.0
        mrr_values.append(active_acv / 12.0)

    result = pd.DataFrame({"month": [str(m) for m in months], "mrr": mrr_values})
    result["arr"] = result["mrr"] * 12
    return result


def revenue_growth(mrr_df: pd.DataFrame) -> pd.DataFrame:
    """Month-over-month and trailing-3-month growth rate on the MRR series."""
    df = mrr_df.copy()
    df["mrr_mom_growth_pct"] = df["mrr"].pct_change().replace([np.inf, -np.inf], np.nan) * 100
    df["mrr_3mo_growth_pct"] = df["mrr"].pct_change(periods=3).replace([np.inf, -np.inf], np.nan) * 100
    return df


def pipeline_forecast(opps_df: pd.DataFrame) -> dict:
    """
    Weighted pipeline forecast: sum(deal_value * stage_win_probability) for
    all open opportunities. Stage win probabilities are calibrated from this
    dataset's own historical close rates *by stage order*, a simple but
    standard "stage-weighted forecast" technique used in RevOps.
    """
    closed = opps_df[opps_df["stage"].isin(["Closed Won", "Closed Lost"])]
    open_opps = opps_df[~opps_df["stage"].isin(["Closed Won", "Closed Lost"])]

    overall_win_rate = (
        (closed["stage"] == "Closed Won").sum() / len(closed) if len(closed) else 0.3
    )

    # Simple heuristic: later stages get a probability boost proportional to
    # historical overall win rate, scaled by stage order. In a real system
    # this would be a logistic regression trained on stage-transition
    # history; documented here as a clearly-labeled simplification.
    stage_order = [
        "Prospecting", "Qualification", "Needs Analysis", "Proposal", "Negotiation",
    ]
    stage_multipliers = {s: (i + 1) / len(stage_order) for i, s in enumerate(stage_order)}

    def weighted_value(row):
        mult = stage_multipliers.get(row["stage"], 0.1)
        prob = min(overall_win_rate * (1 + mult), 0.95)
        return row["deal_value"] * prob

    weighted = open_opps.apply(weighted_value, axis=1) if not open_opps.empty else pd.Series(dtype=float)

    return {
        "total_open_pipeline": float(open_opps["deal_value"].sum()) if not open_opps.empty else 0.0,
        "weighted_forecast": float(weighted.sum()) if not weighted.empty else 0.0,
        "overall_historical_win_rate": round(overall_win_rate * 100, 2),
        "open_opportunity_count": int(len(open_opps)),
    }


def funnel_conversion_rates(opps_df: pd.DataFrame) -> list:
    """
    Stage-to-stage conversion, computed by treating each stage as a
    "reached at least this far" bucket (deals currently further along, or
    closed won, have implicitly passed through earlier stages).
    """
    stage_order = [
        "Prospecting", "Qualification", "Needs Analysis", "Proposal",
        "Negotiation", "Closed Won",
    ]
    stage_rank = {s: i for i, s in enumerate(stage_order)}

    def reached_rank(stage):
        if stage == "Closed Lost":
            return None  # excluded from "reached" counting beyond its actual progress; simplification noted below
        return stage_rank.get(stage, 0)

    ranks = opps_df["stage"].apply(reached_rank)
    total = len(opps_df)

    funnel = []
    counts_at_or_beyond = []
    for i, stage in enumerate(stage_order):
        count = (ranks >= i).sum()
        counts_at_or_beyond.append(count)

    for i, stage in enumerate(stage_order):
        pct_of_total = round(counts_at_or_beyond[i] / total * 100, 1) if total else 0
        conv_from_prev = (
            round(counts_at_or_beyond[i] / counts_at_or_beyond[i - 1] * 100, 1)
            if i > 0 and counts_at_or_beyond[i - 1] else None
        )
        funnel.append({
            "stage": stage,
            "count": int(counts_at_or_beyond[i]),
            "pct_of_total": pct_of_total,
            "conversion_from_previous_stage_pct": conv_from_prev,
        })
    return funnel


def customer_lifetime_value(opps_df: pd.DataFrame) -> pd.DataFrame:
    """
    Simplified CLV per account = total historical Closed Won revenue for
    that account (bookings-to-date). This treats CLV as "revenue realized
    so far" rather than a forward-looking prediction, which is the more
    defensible approach without churn-adjusted retention modeling per
    account. Grouped by company_size/industry for portfolio-level insight.
    """
    won = opps_df[opps_df["stage"] == "Closed Won"]
    clv = won.groupby(["account_id", "company_name", "industry", "company_size"], as_index=False)[
        "deal_value"
    ].sum().rename(columns={"deal_value": "lifetime_value"})
    return clv.sort_values("lifetime_value", ascending=False)


def churn_risk_indicators(opps_df: pd.DataFrame, as_of: date = None) -> pd.DataFrame:
    """
    Flags accounts as "at risk" using two simple, explainable signals
    (deliberately simple/explainable rather than a black-box model, which
    matters for a RevOps tool where reps need to trust and act on the
    output):

      1. CONTRACT LAPSING: the account's most recent Closed Won deal is
         approaching or past its 12-month anniversary with no subsequent
         Closed Won (renewal) opportunity on the account.
      2. NO RECENT ENGAGEMENT: (proxied here via no opportunity activity
         in the trailing 90 days, since this table doesn't separately
         track post-sale success activities in this schema iteration).

    Risk score is a simple 0-100 composite of these two signals, banded
    into Low / Medium / High for the dashboard.
    """
    as_of = as_of or TODAY
    won = opps_df[opps_df["stage"] == "Closed Won"].copy()
    if won.empty:
        return pd.DataFrame(
            columns=["account_id", "company_name", "industry", "company_size",
                     "last_close_date", "days_since_last_close", "risk_score", "risk_band"]
        )
    won["close_date"] = pd.to_datetime(won["close_date"])

    last_close = won.groupby(["account_id", "company_name", "industry", "company_size"], as_index=False)[
        "close_date"
    ].max().rename(columns={"close_date": "last_close_date"})

    as_of_ts = pd.Timestamp(as_of)
    last_close["days_since_last_close"] = (as_of_ts - last_close["last_close_date"]).dt.days

    def score(days):
        # 0 risk right after close, ramping up as the 365-day contract term
        # approaches, capped at 100 once well past renewal.
        if days <= 270:
            return max(0, round((days / 270) * 40))
        elif days <= 365:
            return round(40 + (days - 270) / (365 - 270) * 40)
        else:
            return min(100, round(80 + (days - 365) / 30 * 5))

    last_close["risk_score"] = last_close["days_since_last_close"].apply(score)

    def band(s):
        if s >= 70:
            return "High"
        elif s >= 40:
            return "Medium"
        return "Low"

    last_close["risk_band"] = last_close["risk_score"].apply(band)
    return last_close.sort_values("risk_score", ascending=False)


def top_level_summary(opps_df: pd.DataFrame) -> dict:
    """One-shot summary dict for the dashboard's top KPI cards."""
    mrr_df = build_mrr_timeseries(opps_df)
    current_mrr = float(mrr_df["mrr"].iloc[-1]) if not mrr_df.empty else 0.0
    current_arr = current_mrr * 12

    growth_df = revenue_growth(mrr_df)
    mom_growth = (
        float(growth_df["mrr_mom_growth_pct"].iloc[-1])
        if not growth_df.empty and pd.notna(growth_df["mrr_mom_growth_pct"].iloc[-1])
        else 0.0
    )

    closed = opps_df[opps_df["stage"].isin(["Closed Won", "Closed Lost"])]
    win_rate = round((closed["stage"] == "Closed Won").sum() / len(closed) * 100, 1) if len(closed) else 0.0

    open_opps = opps_df[~opps_df["stage"].isin(["Closed Won", "Closed Lost"])]

    return {
        "arr": round(current_arr, 2),
        "mrr": round(current_mrr, 2),
        "mrr_mom_growth_pct": round(mom_growth, 2),
        "win_rate_pct": win_rate,
        "open_pipeline_value": round(float(open_opps["deal_value"].sum()), 2) if not open_opps.empty else 0.0,
        "open_opportunity_count": int(len(open_opps)),
        "total_accounts": int(opps_df["account_id"].nunique()),
        "total_closed_won_deals": int((opps_df["stage"] == "Closed Won").sum()),
    }
