# API Reference

Base URL (local dev): `http://localhost:5000`

All responses are JSON. All list endpoints support pagination via
`?page=` (default 1) and `?per_page=` (default 50, max 500).

## Health

```
GET /health
```
Returns `{"status": "ok", "service": "revenue-intelligence-api"}`.

## Entity endpoints

### Sales Reps
```
GET /api/sales-reps                 # list, paginated
GET /api/sales-reps?region=West     # filter by region
```

### Accounts
```
GET /api/accounts
GET /api/accounts?industry=Technology
GET /api/accounts?company_size=Enterprise
GET /api/accounts/<account_id>      # includes nested contacts + opportunities
```

### Contacts
```
GET /api/contacts
GET /api/contacts?account_id=42
```

### Opportunities
```
GET /api/opportunities
GET /api/opportunities?stage=Closed Won
GET /api/opportunities?rep_id=5
```

### Activities
```
GET /api/activities
GET /api/activities?opportunity_id=123
```

## Analytics / KPI endpoints

### `GET /api/kpis/summary`
Top-line KPI cards.
```json
{
  "arr": 11994566.93,
  "mrr": 999547.24,
  "mrr_mom_growth_pct": -5.83,
  "win_rate_pct": 36.7,
  "open_pipeline_value": 31655105.67,
  "open_opportunity_count": 294,
  "total_accounts": 1050,
  "total_closed_won_deals": 453
}
```

### `GET /api/kpis/revenue-timeseries`
Monthly MRR/ARR with growth rates. Array of:
```json
{"month": "2026-06", "mrr": 1061407.0, "arr": 12736887.27,
 "mrr_mom_growth_pct": 9.4, "mrr_3mo_growth_pct": 12.1}
```

### `GET /api/kpis/pipeline`
```json
{
  "by_stage": [{"stage": "Proposal", "opportunity_count": 74, "total_value": 6980779.85, "avg_deal_value": 94334.86}],
  "forecast": {"total_open_pipeline": 31655105.67, "weighted_forecast": 18782520.13,
               "overall_historical_win_rate": 36.71, "open_opportunity_count": 294}
}
```

### `GET /api/kpis/funnel`
Array of stage rows with count, % of total, and conversion from the
previous stage.

### `GET /api/kpis/rep-leaderboard`
Per-rep deals won/lost/open, revenue closed, open pipeline value, and
activity count — sorted by revenue closed descending.

### `GET /api/kpis/segmentation`
Account count, total closed revenue, and avg deal value by
industry × company_size.

### `GET /api/kpis/clv?limit=20`
Top accounts by realized lifetime value (sum of Closed Won deal value).

### `GET /api/kpis/churn-risk?band=High`
Accounts flagged with a churn risk score (0–100) and band
(Low/Medium/High). Optional `band` filter.

### `GET /api/kpis/activity-volume`
Total logged activities by type.

## Error responses

```json
{"error": "Account not found"}      // 404
{"error": "Not found"}              // 404, unmatched route
{"error": "Internal server error"}  // 500
```
