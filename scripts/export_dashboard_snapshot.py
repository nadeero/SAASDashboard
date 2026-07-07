"""
scripts/export_dashboard_snapshot.py

Regenerates the embedded static JSON snapshot inside dashboard/index.html
from whatever is currently in the database. Run this after re-seeding
(python -m app.etl.seed) if you want the standalone dashboard file to
reflect the latest data, e.g. before taking portfolio screenshots or
sharing the HTML file without also running the Flask server.

Usage:
    python scripts/export_dashboard_snapshot.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.extensions import db
from app.analytics import queries as q
from app.analytics import kpi

DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


def build_payload(app):
    with app.app_context(), db.engine.connect() as conn:
        opps_df = q.all_opportunities_raw(conn)

        summary = kpi.top_level_summary(opps_df)
        mrr_df = kpi.build_mrr_timeseries(opps_df)
        growth_df = kpi.revenue_growth(mrr_df).fillna(0)
        by_stage = q.pipeline_by_stage(conn)
        forecast = kpi.pipeline_forecast(opps_df)
        funnel = kpi.funnel_conversion_rates(opps_df)
        leaderboard = q.rep_leaderboard(conn)
        segmentation = q.customer_segmentation(conn)
        clv = kpi.customer_lifetime_value(opps_df).head(15)
        churn = kpi.churn_risk_indicators(opps_df).copy()
        churn["last_close_date"] = churn["last_close_date"].astype(str)
        activity_vol = q.activity_volume_by_type(conn)

        return {
            "generated_at": str(kpi.TODAY),
            "summary": summary,
            "revenue_timeseries": growth_df.to_dict(orient="records"),
            "pipeline_by_stage": by_stage.to_dict(orient="records"),
            "forecast": forecast,
            "funnel": funnel,
            "rep_leaderboard": leaderboard.to_dict(orient="records"),
            "segmentation": segmentation.to_dict(orient="records"),
            "clv_top": clv.to_dict(orient="records"),
            "churn_risk_top": churn.head(15).to_dict(orient="records"),
            "churn_band_counts": churn["risk_band"].value_counts().to_dict(),
            "activity_volume": activity_vol.to_dict(orient="records"),
        }


def main():
    app = create_app("development")
    payload = build_payload(app)
    json_str = json.dumps(payload, default=str)

    html = DASHBOARD_HTML.read_text()
    new_html = re.sub(
        r'(<script id="dashboard-data" type="application/json">)(.*?)(</script>)',
        lambda m: m.group(1) + json_str + m.group(3),
        html,
        flags=re.S,
    )
    DASHBOARD_HTML.write_text(new_html)
    print(f"Updated embedded snapshot in {DASHBOARD_HTML} ({len(json_str)} bytes of JSON).")


if __name__ == "__main__":
    main()
