"""
app/etl/seed.py

ETL orchestration: Extract (generate synthetic data in memory) -> Transform
(none needed here since generate_data already produces ORM-ready objects) ->
Load (bulk insert into the configured database).

DESIGN DECISION: We wipe and recreate all tables (db.drop_all() + db.create_all())
before seeding rather than trying to "upsert". This is a demo/portfolio dataset
generator, not a production migration tool -- idempotent, reproducible seeding
is more valuable here than incremental updates. Real production ETL against a
live CRM (e.g. Salesforce -> warehouse) would instead use incremental
upserts keyed on external IDs; that pattern is noted in docs/ARCHITECTURE.md.

DESIGN DECISION: We insert in strict dependency order (reps and accounts
first, then contacts/opportunities which reference them, then activities
last) and use session.bulk_save_objects-style adds with periodic commits
to avoid holding tens of thousands of objects pending in one transaction.

Run with:  python -m app.etl.seed
"""

import time
import sys

from app import create_app
from app.extensions import db
from app.etl.generate_data import generate_full_dataset


def seed_database(app=None, n_accounts=1050, n_reps=28, opp_target=1550, verbose=True):
    app = app or create_app("development")

    with app.app_context():
        t0 = time.time()
        if verbose:
            print("Dropping and recreating all tables...")
        db.drop_all()
        db.create_all()

        if verbose:
            print("Generating synthetic dataset in memory...")
        dataset = generate_full_dataset(n_accounts=n_accounts, n_reps=n_reps, opp_target=opp_target)

        if verbose:
            print(f"  reps={len(dataset['reps'])} accounts={len(dataset['accounts'])} "
                  f"contacts={len(dataset['contacts'])} opportunities={len(dataset['opportunities'])} "
                  f"activities={len(dataset['activities'])}")

        # Order matters: reps/accounts have no FK dependencies, contacts and
        # opportunities depend on accounts (and opportunities on reps),
        # activities depend on opportunities and reps.
        if verbose:
            print("Loading sales_reps...")
        db.session.add_all(dataset["reps"])
        db.session.flush()

        if verbose:
            print("Loading accounts...")
        db.session.add_all(dataset["accounts"])
        db.session.flush()

        if verbose:
            print("Loading contacts...")
        db.session.add_all(dataset["contacts"])
        db.session.flush()

        if verbose:
            print("Loading opportunities...")
        db.session.add_all(dataset["opportunities"])
        db.session.flush()

        if verbose:
            print("Loading activities...")
        db.session.add_all(dataset["activities"])
        db.session.commit()

        elapsed = time.time() - t0
        if verbose:
            print(f"Done in {elapsed:.1f}s. Database ready at "
                  f"{app.config['SQLALCHEMY_DATABASE_URI']}")

        return {
            "reps": len(dataset["reps"]),
            "accounts": len(dataset["accounts"]),
            "contacts": len(dataset["contacts"]),
            "opportunities": len(dataset["opportunities"]),
            "activities": len(dataset["activities"]),
            "elapsed_seconds": round(elapsed, 2),
        }


if __name__ == "__main__":
    stats = seed_database()
    sys.exit(0)
