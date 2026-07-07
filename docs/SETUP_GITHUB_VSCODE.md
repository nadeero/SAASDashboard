# Step-by-Step: GitHub + VS Code Setup

This walks through turning the downloaded project into a real GitHub
repository with a clean commit history, developed in VS Code.

## Step 1 — Create the GitHub repository

1. Go to github.com → **New repository**.
2. Name it something like `saas-revenue-intelligence-platform`.
3. Set it **Public** (this is a portfolio piece).
4. **Do not** initialize with a README/.gitignore/license — you already
   have those in the download. Click **Create repository**.
5. Copy the remote URL GitHub shows you, e.g.
   `https://github.com/<you>/saas-revenue-intelligence-platform.git`

## Step 2 — Unzip and open in VS Code

```bash
unzip saas-revenue-intelligence.zip -d saas-revenue-intelligence-platform
cd saas-revenue-intelligence-platform
code .
```

In VS Code, install these extensions when prompted (or manually):
- **Python** (ms-python.python)
- **Pylance**
- **SQLite Viewer** (optional, lets you browse `data/revenue_intelligence.db` visually)

## Step 3 — Create the virtual environment (in VS Code's integrated terminal)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

VS Code should prompt "Select a Python interpreter" — choose the one
inside `./venv`. If it doesn't prompt, open the Command Palette
(`Cmd/Ctrl+Shift+P`) → **Python: Select Interpreter** → pick `venv`.

## Step 4 — Generate the database

```bash
python -m app.etl.seed
```

You should see progress output ending in something like:
```
Loading activities...
Done in 4.2s. Database ready at sqlite:////.../data/revenue_intelligence.db
```

## Step 5 — Run the tests

```bash
pytest -v
```

All tests should pass. This is worth running again after any change —
it's your safety net.

## Step 6 — Run the API

```bash
python run.py
```

Visit `http://localhost:5000/health` in a browser to confirm it's live,
then try `http://localhost:5000/api/kpis/summary`.

## Step 7 — Open the dashboard

Open `dashboard/index.html` directly in a browser (or right-click →
**Open with Live Server** if you have that VS Code extension). It loads
fully from an embedded data snapshot. To see it pull from your *running*
API instead, type `http://localhost:5000` into the box at the bottom and
click **Load from live API**.

If you re-seed the database and want the standalone dashboard file to
reflect the new data (e.g. before a portfolio screenshot), run:
```bash
python scripts/export_dashboard_snapshot.py
```

## Step 8 — Commit in logical steps (not one giant commit)

This is what makes the repo *read* like real engineering work instead of
a single dump. Suggested commit sequence:

```bash
git init
git branch -M main
git remote add origin https://github.com/<you>/saas-revenue-intelligence-platform.git

git add config.py app/__init__.py app/extensions.py app/models.py .gitignore requirements.txt
git commit -m "Add project scaffolding and SQLAlchemy schema"

git add app/etl/
git commit -m "Add synthetic B2B SaaS dataset generator and ETL loader"

git add app/analytics/
git commit -m "Add SQL analytics queries and pandas KPI calculations"

git add app/api/ run.py
git commit -m "Add Flask REST API with entity and KPI endpoints"

git add dashboard/
git commit -m "Add analytics dashboard (Chart.js, live-API connector)"

git add tests/
git commit -m "Add pytest suite: models, ETL, analytics, API"

git add docs/ README.md scripts/
git commit -m "Add documentation and dashboard snapshot export script"

git push -u origin main
```

(Adjust paths/messages as needed if you've already made other edits —
the point is several meaningful commits, not necessarily this exact
split.)

## Step 9 — Polish for portfolio presentation

- Add a screenshot of the running dashboard to the top of `README.md`
  (drag an image into GitHub's web editor, or commit it to
  `docs/screenshot.png` and reference it: `![Dashboard](docs/screenshot.png)`).
- Add topics/tags to the GitHub repo (`revenue-operations`, `flask`,
  `sqlalchemy`, `pandas`, `saas-analytics`) so it's discoverable.
- Consider adding a short GIF of clicking through the dashboard, using a
  tool like [Kap](https://getkap.co/) or [ScreenToGif](https://www.screentogif.com/).
- If you want a live demo link, the Flask API + dashboard can be deployed
  to Render, Railway, or Fly.io for free; the dashboard's static mode
  means it also works perfectly well with **just the HTML file hosted on
  GitHub Pages**, no server required.

## Common issues

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | Make sure you're running commands from the project root, and your venv is activated |
| Tests fail with a DB error | Delete `data/revenue_intelligence.db` and re-run `python -m app.etl.seed` |
| Dashboard shows old numbers | Re-run `python scripts/export_dashboard_snapshot.py` after reseeding |
| Port 5000 already in use (common on macOS due to AirPlay) | Run `PORT=5001 python run.py` instead |
