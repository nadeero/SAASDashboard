"""
run.py

Local development entry point. In production, use gunicorn against the
factory directly, e.g.:

    gunicorn "app:create_app('production')" --bind 0.0.0.0:8000 --workers 4
"""

import os
from app import create_app

app = create_app(os.environ.get("FLASK_ENV", "development"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=app.config.get("DEBUG", False))
