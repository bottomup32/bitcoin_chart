"""Apply pending SQL migrations from db/migrations/ in filename order.

Usage: python -m jobs.apply_migrations
Each migration runs in its own transaction and is recorded in
schema_migrations, so re-running is a no-op.
"""

from pathlib import Path

from db.client import get_conn

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def main() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                    version    text primary key,
                    applied_at timestamptz not null default now()
                )
                """
            )
            cur.execute("select version from schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            with conn.cursor() as cur:
                cur.execute(path.read_text())
                cur.execute(
                    "insert into schema_migrations (version) values (%s)", (path.name,)
                )
            conn.commit()
            print(f"applied {path.name}")

    print("migrations up to date")


if __name__ == "__main__":
    main()
