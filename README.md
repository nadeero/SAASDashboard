# Northbeam &mdash; SaaS Revenue Intelligence Platform

A full-stack Revenue Operations analytics platform simulating a real B2B SaaS
sales organization: pipeline, revenue, customer accounts, and sales team
performance, with a Flask REST API and a live analytics dashboard.

Built to demonstrate the kind of system a Revenue Operations / Sales
Engineering / Analytics team would actually run internally.

## What's inside

| Layer | Tech | Purpose |
|---|---|---|
| Database | SQLite (Postgres-portable schema) | 5-table relational schema with FKs |
| ORM | SQLAlchemy 2.0 | Schema definition, constraints, relationships |
| ETL | Python | Synthetic dataset generator + loader |
| Analytics | pandas + raw SQL | KPI calculations, forecasting, churn/CLV |
| API | Flask + Flask-SQLAlchemy | REST endpoints for entities + KPIs |
| Dashboard | HTML/CSS/JS + Chart.js | ARR/MRR, funnel, leaderboard, segmentation |
| Tests | pytest | Model, ETL, analytics, and API test coverage |

## Quickstart

```bash
# 1. Clone and enter the repo
git clone <your-repo-url>.git
cd saas-revenue-intelligence

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate the database (1000+ accounts, 1500+ opportunities, etc.)
python -m app.etl.seed

# 5. Run the test suite
pytest -v

# 6. Start the API
python run.py
# API now live at http://localhost:5000  (try http://localhost:5000/health)

# 7. Open the dashboard
open dashboard/index.html          # macOS
# or just double-click the file, or `start dashboard/index.html` on Windows
```

The dashboard opens fully populated from an embedded data snapshot (no
server required to view it). To see it pull live from your running API
instead, type `http://localhost:5000` into the "Load from live API" box
at the bottom of the dashboard and click the button.

## Project layout

```
saas-revenue-intelligence/
├── app/
│   ├── __init__.py           # Flask application factory
│   ├── extensions.py         # SQLAlchemy singleton
│   ├── models.py             # ORM schema (5 tables + relationships)
│   ├── api/
│   │   └── routes.py         # REST endpoints (entities + KPIs)
│   ├── analytics/
│   │   ├── queries.py        # Raw SQL analytics (joins, aggregates)
│   │   └── kpi.py            # pandas-based KPI logic (ARR/MRR, forecast, CLV, churn)
│   └── etl/
│       ├── generate_data.py  # Synthetic dataset generator
│       └── seed.py           # Loads generated data into the DB
├── dashboard/
│   ├── index.html            # Dashboard shell + embedded data snapshot
│   └── dashboard.js           # Chart rendering + live-API connector
├── scripts/
│   └── export_dashboard_snapshot.py  # Refresh the embedded dashboard data
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_analytics.py
│   ├── test_api.py
│   └── test_etl.py
├── docs/
│   ├── ARCHITECTURE.md        # Design decisions, schema rationale, ARR/MRR definitions
│   ├── API.md                 # Endpoint reference
│   └── SETUP_GITHUB_VSCODE.md # Step-by-step repo + VS Code workflow
├── config.py
├── run.py
└── requirements.txt
```

## The dataset

Generated deterministically (fixed random seed) so results are reproducible
run to run:

- **1,050+ accounts** across 15 industries and 3 size segments (SMB /
  Mid-Market / Enterprise)
- **2,100+ contacts**
- **1,500+ opportunities**, with realistic stage progression, deal sizing
  by company size, and rep-skill-driven win rates
- **10,000+ activities** logged against opportunities
- **28 sales reps** across 5 regions

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full rationale
behind every schema, ETL, and analytics decision.

## Analytics included

- ARR / MRR (12-month contract-term model) and month-over-month growth
- Stage-weighted revenue forecast
- Sales funnel conversion (stage-to-stage)
- Sales rep leaderboard (win rate, revenue closed, activity volume)
- Customer segmentation (industry × company size)
- Customer lifetime value (realized bookings-to-date)
- Churn risk scoring (contract-lapse + engagement signals)

## Migrating to PostgreSQL

The schema and all queries are written to be Postgres-compatible from day
one. To migrate:

1. `pip install psycopg2-binary`
2. Set `DATABASE_URL=postgresql://user:pass@host:5432/revenue_intelligence`
3. Run `python -m app.etl.seed` against that URL (or write an Alembic
   migration if you want to preserve existing Postgres data instead of
   reseeding)

No model or query code changes are required — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#postgresql-migration) for
details.
