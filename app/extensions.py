"""
app/extensions.py

Holds the singleton SQLAlchemy() instance.

DESIGN DECISION: The `db` object is created here, NOT inside models.py and
NOT inside the app factory. This avoids circular imports: models.py imports
`db` from here, and the app factory (app/__init__.py) also imports `db`
from here and calls db.init_app(app). This is the standard "Flask
application factory + extensions module" pattern used in production Flask
codebases.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
