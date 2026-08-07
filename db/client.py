"""Postgres connection helper.

All DB access (migrations, jobs, local CLI) goes through the Supabase Postgres
connection string in SUPABASE_DB_URL. The service-role path bypasses RLS, so
the real controls are secret management and never printing holdings in CI logs
(PLAN.md §2, §6).
"""

import os

import psycopg


def get_conn() -> psycopg.Connection:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit(
            "SUPABASE_DB_URL is not set. "
            "Use the Supabase 'Connection string' (URI) with the database password."
        )
    return psycopg.connect(url)
