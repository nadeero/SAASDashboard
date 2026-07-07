"""
tests/test_api.py

Integration tests for the Flask REST API: status codes, response shapes,
pagination, and filtering, exercised against the seeded in-memory DB.
"""


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_list_accounts(client, seeded_db):
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert {"account_id", "company_name", "industry"} <= body["items"][0].keys()


def test_list_accounts_filter_by_industry(client, seeded_db):
    resp = client.get("/api/accounts?industry=Technology")
    body = resp.get_json()
    assert body["total"] == 1
    assert body["items"][0]["company_name"] == "Acme Corp"


def test_get_single_account_includes_nested_data(client, seeded_db):
    acc_id = seeded_db["accounts"][0].account_id
    resp = client.get(f"/api/accounts/{acc_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["company_name"] == "Acme Corp"
    assert len(body["contacts"]) == 1
    assert len(body["opportunities"]) == 1


def test_get_nonexistent_account_returns_404(client, seeded_db):
    resp = client.get("/api/accounts/999999")
    assert resp.status_code == 404


def test_list_opportunities_filter_by_stage(client, seeded_db):
    resp = client.get("/api/opportunities?stage=Closed Won")
    body = resp.get_json()
    assert body["total"] == 1
    assert body["items"][0]["opportunity_name"] == "Acme - New Business"


def test_pagination_bounds_enforced(client, seeded_db):
    # per_page should be clamped to MAX_PAGE_SIZE, never error out
    resp = client.get("/api/accounts?per_page=999999")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["per_page"] <= 500


def test_kpi_summary_endpoint(client, seeded_db):
    resp = client.get("/api/kpis/summary")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "arr" in body
    assert "mrr" in body
    assert body["win_rate_pct"] == 50.0


def test_kpi_pipeline_endpoint(client, seeded_db):
    resp = client.get("/api/kpis/pipeline")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "by_stage" in body
    assert "forecast" in body


def test_kpi_rep_leaderboard_endpoint(client, seeded_db):
    resp = client.get("/api/kpis/rep-leaderboard")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 2
    names = {row["rep_name"] for row in body}
    assert names == {"Jane Doe", "John Smith"}


def test_kpi_churn_risk_endpoint_band_filter(client, seeded_db):
    resp = client.get("/api/kpis/churn-risk")
    assert resp.status_code == 200
    all_bands = {row["risk_band"] for row in resp.get_json()}
    assert all_bands <= {"Low", "Medium", "High"}


def test_kpi_clv_endpoint_respects_limit(client, seeded_db):
    resp = client.get("/api/kpis/clv?limit=1")
    body = resp.get_json()
    assert len(body) <= 1
