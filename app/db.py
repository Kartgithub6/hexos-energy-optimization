"""
app.db
======
PostgreSQL persistence for the Streamlit demo: saved scenarios and run
history. Deliberately kept OUTSIDE the `engine` package -- the core optimizer
has no database dependency; only this UI layer does. Scenario scripts and
tests never touch this module.

Connection: reads DATABASE_URL from an environment variable, or from
Streamlit secrets (.streamlit/secrets.toml, which must be gitignored -- never
commit real database credentials). If neither is set, every function here
returns None / does nothing, so the app degrades gracefully instead of
crashing when no database is configured.
"""
from __future__ import annotations
import os

try:
    import psycopg2
    import psycopg2.extras
    _HAVE_PSYCOPG2 = True
except ImportError:
    _HAVE_PSYCOPG2 = False


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


def get_connection():
    """Return a live connection, or None if no database is configured."""
    if not _HAVE_PSYCOPG2:
        return None
    url = _database_url()
    if not url:
        return None
    try:
        return psycopg2.connect(url)
    except Exception:
        return None


SCHEMA = """
CREATE TABLE IF NOT EXISTS scenarios (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    day_mode TEXT NOT NULL,
    day_value TEXT NOT NULL,
    base_price REAL NOT NULL,
    peak_ratio REAL NOT NULL,
    use_chp BOOLEAN NOT NULL,
    use_hp BOOLEAN NOT NULL,
    use_battery BOOLEAN NOT NULL,
    use_wood BOOLEAN NOT NULL,
    use_gas BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id SERIAL PRIMARY KEY,
    scenario_name TEXT,
    day_label TEXT NOT NULL,
    cost REAL NOT NULL,
    peak_import REAL NOT NULL,
    pv_used REAL NOT NULL,
    heat_dumped REAL NOT NULL,
    technologies TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_schema(conn):
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    conn.commit()


def save_scenario(conn, name, day_mode, day_value, base_price, peak_ratio,
                  use_chp, use_hp, use_battery, use_wood, use_gas):
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scenarios (name, day_mode, day_value, base_price, peak_ratio,
                                   use_chp, use_hp, use_battery, use_wood, use_gas)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                day_mode = EXCLUDED.day_mode, day_value = EXCLUDED.day_value,
                base_price = EXCLUDED.base_price, peak_ratio = EXCLUDED.peak_ratio,
                use_chp = EXCLUDED.use_chp, use_hp = EXCLUDED.use_hp,
                use_battery = EXCLUDED.use_battery, use_wood = EXCLUDED.use_wood,
                use_gas = EXCLUDED.use_gas, created_at = now()
        """, (name, day_mode, day_value, base_price, peak_ratio,
              use_chp, use_hp, use_battery, use_wood, use_gas))
    conn.commit()


def list_scenario_names(conn) -> list[str]:
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM scenarios ORDER BY created_at DESC")
        return [r[0] for r in cur.fetchall()]


def load_scenario(conn, name: str) -> dict | None:
    if conn is None:
        return None
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM scenarios WHERE name = %s", (name,))
        row = cur.fetchone()
        return dict(row) if row else None


def log_run(conn, scenario_name, day_label, cost, peak_import, pv_used,
           heat_dumped, technologies):
    if conn is None:
        return
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO runs (scenario_name, day_label, cost, peak_import,
                              pv_used, heat_dumped, technologies)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (scenario_name, day_label, cost, peak_import, pv_used, heat_dumped, technologies))
    conn.commit()


def get_run_history(conn, limit: int = 50):
    if conn is None:
        return []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT %s", (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_cost_by_daytype(conn):
    """Aggregation query: average cost and run count per day label."""
    if conn is None:
        return []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT day_label, AVG(cost) AS avg_cost, COUNT(*) AS n_runs
            FROM runs GROUP BY day_label ORDER BY avg_cost DESC
        """)
        return [dict(r) for r in cur.fetchall()]
