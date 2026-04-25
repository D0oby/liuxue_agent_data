from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from src.config import Settings

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None


def _require_psycopg():
    if psycopg is None:
        raise ModuleNotFoundError(
            "psycopg is not installed. Run `pip install -e .` in usyd_pg_import first."
        )


@contextmanager
def connect(settings: Settings):
    _require_psycopg()
    conn = psycopg.connect(settings.database_url)
    try:
        yield conn
    finally:
        conn.close()


def apply_migrations(conn, migrations_dir: Path) -> None:
    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        raise FileNotFoundError(f"No migration files found in {migrations_dir}")

    with conn.cursor() as cur:
        for migration_file in migration_files:
            cur.execute(migration_file.read_text(encoding="utf-8"))

