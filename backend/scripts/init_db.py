"""
Creates the database tables in Neon (safe to run more than once).

Run from the backend folder:
    python scripts/init_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # so "app" can be imported

import psycopg  # noqa: E402

from app import config  # noqa: E402

if not config.DATABASE_URL:
    sys.exit("DATABASE_URL is empty. Open backend/.env and paste your Neon connection string after DATABASE_URL=")

schema = (Path(config.BACKEND_DIR) / "app" / "schema.sql").read_text(encoding="utf-8")
print("Connecting to the database ...")
try:
    with psycopg.connect(config.DATABASE_URL, connect_timeout=20) as conn:
        conn.execute(schema)
        postgis = conn.execute("SELECT postgis_version()").fetchone()[0]
        tables = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN ('hotspots', 'reports') ORDER BY 1")]
except psycopg.OperationalError as exc:
    sys.exit(f"Could not connect. Check the DATABASE_URL line in backend/.env.\nDetails: {exc}")

print("PostGIS version:", postgis)
print("Tables ready:   ", ", ".join(tables))
print("Database setup complete.")
