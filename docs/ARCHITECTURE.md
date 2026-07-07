# Architecture & Design Decisions

This document explains *why* the system is built the way it is — the
things a code review or a system-design interview would ask about.

## 1. Schema design

### Surrogate keys
Every table uses an autoincrement integer primary key rather than a
natural key (e.g. `email` for contacts). Natural keys change (a contact
switches email, a company rebrands); surrogate keys don't. This is
standard OLTP schema practice and matches how Salesforce/HubSpot-style
CRMs are actually modeled.

### Foreign key delete behavior
- `accounts → contacts`, `accounts → opportunities`: **CASCADE**. A
  contact or opportunity has no meaning without its parent account, so
  deleting the account should remove them.
- `opportunities → activities`: **CASCADE**, same reasoning.
- `sales_reps → opportunities` / `sales_reps → activities`: **SET NULL**.
  Deleting a rep (e.g. they leave the company) should *not* destroy the
  historical record of deals and activity against their name — that would
  corrupt revenue history and audit trails. In a real system you'd
  reassign these records to a new owner before/instead of deleting the
  rep; SET NULL prevents silent data loss in the meantime.

### Enums as indexed strings, not native SQL ENUM
SQLite has no native ENUM type, and Postgres's ENUM type requires
`ALTER TYPE ... ADD VALUE` migrations every time a new value is added
(e.g. a new pipeline stage) — awkward for a fast-moving sales org.
Instead, stage/company_size/activity_type are `String` columns validated
at the application layer (`app/models.py` `STAGE_CHOICES`, etc., plus a
`CheckConstraint` at the DB level as a second line of defense). This is
also what keeps the schema trivially portable between SQLite and
Postgres with zero changes.

### Money as `Numeric(12,2)`, never `Float`
Floats introduce binary rounding error. A revenue platform whose ARR
doesn't reconcile to the penny is not credible. `Numeric` maps to
`DECIMAL` in both SQLite and Postgres.

### Audit timestamps vs. business dates
Every table has `created_at`/`updated_at` (when the *row* was written) in
addition to business-meaningful dates like `close_date` and `hire_date`
(when the *event* happened). Real CRMs track both separately — a deal is
often backfilled into the system days after it was actually closed — and
conflating the two would make "when did this happen" queries wrong.

## 2. Synthetic data generation

### No Faker dependency
`app/etl/generate_data.py` deliberately avoids the `Faker` library.
Generic fake-data libraries produce names and companies with no
SaaS-specific structure. Instead, we hand-curate small vocabularies
(industries, company name parts, job titles) and layer real sales-motion
logic on top — which is what actually makes the dataset useful for
analytics rather than just "realistic-looking" noise. It also means the
project has one fewer external dependency and works fully offline.

### Reproducibility
`random.seed(SEED)` at generation time makes every run of
`generate_full_dataset()` byte-for-byte identical. This matters for a
portfolio project: the numbers you screenshot in your README stay in
sync with what a reviewer sees when they clone and run it themselves.

### The realism logic that matters
Random data without structure produces analytics that all look the same
(flat leaderboards, flat win rates). This generator deliberately encodes:

- **Deal size scales with company size** via a log-normal distribution
  per segment (SMB centers ~$10K, Mid-Market ~$40K, Enterprise ~$200K),
  matching real ACV (annual contract value) patterns.
- **Win rate varies by rep** — each rep gets a hidden skill multiplier
  (0.55×–1.35×) applied to a segment base win rate, so the leaderboard
  has a real spread instead of noise around one number.
- **Win rate varies by segment** — Enterprise deals are harder to close
  (base 27%) than SMB (base 42%), reflecting longer sales cycles and more
  stakeholders.
- **Stage progression is time-aware** — an opportunity's stage is derived
  from how much of its expected sales cycle has elapsed since
  `created_date`, not assigned independently at random. This is what
  makes the funnel and pipeline-by-stage numbers behave sensibly (recent
  opportunities cluster in early stages; older ones are mostly closed).
- **Activity volume scales with deal complexity** — bigger and
  later-stage deals accumulate more logged touchpoints, matching real
  seller behavior.

## 3. Analytics layer: SQL vs. pandas split

`app/analytics/queries.py` (raw SQL via SQLAlchemy `text()`) answers "what
happened" — joins and aggregates the database engine can compute
natively and efficiently. `app/analytics/kpi.py` (pandas) answers "so
what" — derived metrics that need row-level manipulation, rolling
windows, or simple modeling that's awkward to express in SQL (MRR
time-series with 12-month contract-term windows, stage-weighted
forecasting, churn scoring).

### The join fan-out bug (and why it's called out)
An earlier version of `rep_leaderboard()` and `account_revenue_detail()`
joined `opportunities` directly to `activities` in one query, then
`SUM`ed `deal_value` in the same `GROUP BY`. This is a classic and easy
mistake: joining a parent to a one-to-many child multiplies every parent
row once per child row, so `SUM(deal_value)` was being inflated by the
number of activities logged against each deal (sometimes 4–8×). It was
caught in this project by writing a regression test
(`tests/test_analytics.py::test_rep_leaderboard_no_fanout`) with a small,
hand-computable seeded dataset where the correct answer was known in
advance — not by inspecting the large synthetic dataset, where an
inflated-but-plausible-looking number is easy to miss. The fix aggregates
each child table independently in a subquery before joining back to the
parent, which is the general pattern for avoiding fan-out whenever a
one-to-many-to-many join is involved.

### ARR / MRR definition
ARR/MRR are ambiguous terms across companies, so the exact definition
used here is documented in `app/analytics/kpi.py`:
- Every Closed Won opportunity's `deal_value` is treated as an **annual
  contract value (ACV)**.
- **MRR** for a given month = sum of `ACV / 12` for every contract whose
  12-month term covers that month (i.e., signed within the trailing 12
  months and not yet lapsed).
- **ARR** = `MRR × 12` (the standard SaaS convention: an annualized
  run-rate of currently active contracts, not simply "bookings in the
  last 12 months").

This is a simplification of real subscription billing (no upgrades,
downgrades, multi-year terms, or usage-based components) but is the
standard simplification used in RevOps modeling exercises, and is
explicitly documented as such rather than presented as more precise than
it is.

### Churn risk scoring
Two explainable signals, not a black-box model — RevOps teams need to
trust and act on this output:
1. **Contract lapsing**: days since the account's last Closed Won deal,
   scored against the assumed 12-month term.
2. A composite 0–100 score banded into Low/Medium/High.

A real implementation would add engagement recency (support tickets,
product usage, NPS) as additional signals; this is noted as a natural
extension in the code comments.

## 4. API design

- **Application factory pattern** (`create_app()`) rather than a
  module-level `app = Flask(__name__)`, so tests can spin up isolated
  app instances against an in-memory SQLite DB without touching the dev
  database file.
- **Blueprint-based routing** (`app/api/routes.py` registered under
  `/api`) to keep the route surface organized and independently testable.
- **Server-enforced pagination caps** (`MAX_PAGE_SIZE` in `config.py`) so
  list endpoints can't accidentally return the entire table as the
  dataset grows.
- **Analytics endpoints return pre-shaped JSON** (not raw ORM dumps) so
  the dashboard can render directly from the response without
  client-side reshaping.

## 5. PostgreSQL migration

Nothing in `app/models.py` or `app/analytics/queries.py` is SQLite-specific:
- Data types (`Numeric`, `Date`, `DateTime`, `String`, `Text`) all map
  directly to Postgres equivalents.
- The only SQLite-specific SQL is `strftime('%Y-%m', close_date)` in
  `queries.monthly_revenue()` — the Postgres equivalent is
  `to_char(close_date, 'YYYY-MM')`. This is the one query to adjust if
  you migrate; it's called out here explicitly rather than left for
  someone to discover via a runtime error.

To migrate:
```bash
pip install psycopg2-binary
export DATABASE_URL=postgresql://user:pass@host:5432/revenue_intelligence
python -m app.etl.seed  # recreates schema + reseeds against Postgres
```

## 6. Testing strategy

- **`tests/test_models.py`** — ORM-level: relationships, cascade
  behavior, validation (`@validates` rejecting invalid stages).
- **`tests/test_analytics.py`** — uses a small, hand-seeded dataset
  (`conftest.py::seeded_db`) where expected KPI values can be computed by
  hand and asserted exactly. This is what catches correctness bugs (like
  the fan-out issue above) that are invisible against a large randomly
  generated dataset.
- **`tests/test_etl.py`** — exercises the full-scale synthetic generator,
  but only asserts *structural* properties (volume thresholds, valid enum
  values, referential consistency, reproducibility) since exact values
  aren't hand-computable at that scale.
- **`tests/test_api.py`** — integration tests against the Flask test
  client: status codes, pagination bounds, filter params, 404 handling.

## 7. What a production version would add

This is a portfolio/demo system; a production RevOps platform would
additionally need:
- Incremental ETL (upserts keyed on external CRM IDs) instead of
  drop-and-reseed, likely orchestrated with Airflow/Dagster
- Alembic migrations instead of `db.create_all()`
- Authentication/authorization on the API (this demo has none)
- A trained (not heuristic) forecasting model, backtested against actual
  close outcomes
- Real subscription-billing data (upgrades, downgrades, multi-year terms)
  instead of the ACV/12 simplification
- Data quality monitoring (e.g. Great Expectations) on the ETL pipeline
