"""Read back a stored daily report — locally, with no LLM calls.

The report lives in the reports table (never in git, never in CI logs), so
reading it needs a DB connection. This is the low-friction way to see it and
to test email delivery without re-running the agents — re-sending a stored
report costs zero tokens.

Usage:
  python -m jobs.show_report                 # print the latest report
  python -m jobs.show_report --list          # list stored reports
  python -m jobs.show_report --run-date 2026-08-06
  python -m jobs.show_report --email         # re-send the latest by email
"""

from __future__ import annotations

import argparse
from datetime import date

from adapters.resend_email import send_email
from db.client import get_conn


def _fetch(cur, run_date: date | None):
    if run_date:
        cur.execute(
            """
            select r.run_date, rep.body_md, rep.sent_at
            from reports rep join runs r on r.id = rep.run_id
            where r.run_date = %s
            order by rep.id desc limit 1
            """,
            (run_date,),
        )
    else:
        cur.execute(
            """
            select r.run_date, rep.body_md, rep.sent_at
            from reports rep join runs r on r.id = rep.run_id
            order by rep.id desc limit 1
            """
        )
    return cur.fetchone()


def main() -> int:
    parser = argparse.ArgumentParser(prog="show_report")
    parser.add_argument("--run-date", type=date.fromisoformat,
                        help="report for a specific session (YYYY-MM-DD)")
    parser.add_argument("--list", action="store_true", help="list stored reports")
    parser.add_argument("--email", action="store_true",
                        help="re-send it via Resend (no LLM calls)")
    args = parser.parse_args()

    with get_conn() as conn, conn.cursor() as cur:
        if args.list:
            cur.execute(
                """
                select r.run_date, length(rep.body_md), rep.sent_at
                from reports rep join runs r on r.id = rep.run_id
                order by rep.id desc limit 30
                """
            )
            rows = cur.fetchall()
            if not rows:
                print("no reports stored yet — run jobs.run_advise first")
                return 0
            print(f"{'run_date':<12} {'chars':>7}  sent_at")
            for run_date, size, sent_at in rows:
                print(f"{run_date!s:<12} {size:>7}  {sent_at or '-'}")
            return 0

        row = _fetch(cur, args.run_date)
        if row is None:
            print("no report found — run jobs.run_advise first")
            return 1
        run_date, body_md, sent_at = row

        if args.email:
            sent, reason = send_email(f"일일 포트폴리오 브리핑 — {run_date}", body_md)
            print(f"email: {reason}")
            if sent:
                cur.execute(
                    """
                    update reports set sent_at = now()
                    where id = (
                        select rep.id from reports rep join runs r on r.id = rep.run_id
                        where r.run_date = %s order by rep.id desc limit 1
                    )
                    """,
                    (run_date,),
                )
                conn.commit()
            return 0 if sent else 1

        print(body_md)
        if sent_at:
            print(f"\n_(emailed at {sent_at})_")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
