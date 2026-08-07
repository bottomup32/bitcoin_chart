"""Local-only portfolio CLI — the ingestion path for Fidelity data.

This runs on the user's machine, parses CSVs locally, and upserts straight to
Supabase. CSVs and holdings never touch git or CI (PLAN.md §1 [2], §6).

Commands:
  python -m jobs.ingest_portfolio account-add --name brokerage --tax-type taxable
  python -m jobs.ingest_portfolio seed-lots lots.csv
  python -m jobs.ingest_portfolio activity Activity.csv --account brokerage

seed-lots CSV columns (self-authored, from Fidelity's per-position lot detail
screen — the Positions CSV has no lot data):
  account,ticker,qty,cost_basis,acquired_at        # cost_basis per share, date YYYY-MM-DD

activity ingests Fidelity's Activity/History CSV going forward:
  buys/reinvestments -> new tax_lots (reinvest flagged drip)
  dividends          -> cash_events
  sells              -> FIFO realized_events (wash-sale adjustment lands in phase 2)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from datetime import date
from pathlib import Path

from adapters.fidelity_activity import ActivityRow, parse_activity_csv
from core.lots import OpenLot, match_fifo
from core.wash_sale import (
    LossSlice,
    ReplacementBuy,
    evaluate_wash_sale,
    wash_sale_window,
)
from db.client import get_conn


def _ref(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:24]


def _account_id(cur, name: str) -> int:
    cur.execute("select id from accounts where name = %s", (name,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"account '{name}' not found — create it with account-add first")
    return row[0]


def cmd_account_add(args) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into accounts (name, broker, tax_type, owner)
            values (%s, %s, %s, %s)
            on conflict (name) do update
                set broker = excluded.broker,
                    tax_type = excluded.tax_type,
                    owner = excluded.owner
            """,
            (args.name, args.broker, args.tax_type, args.owner),
        )
        conn.commit()
    print(f"account '{args.name}' ready")


def cmd_seed_lots(args) -> None:
    rows = list(csv.DictReader(Path(args.csv).open()))
    if not rows:
        raise SystemExit("empty CSV")
    inserted = skipped = 0
    with get_conn() as conn, conn.cursor() as cur:
        for i, row in enumerate(rows):
            account_id = _account_id(cur, row["account"].strip())
            ticker = row["ticker"].strip().upper()
            qty = float(row["qty"])
            cost_basis = float(row["cost_basis"])
            acquired_at = date.fromisoformat(row["acquired_at"].strip())
            ref = "seed:" + _ref(row["account"], ticker, qty, cost_basis, acquired_at, i)
            cur.execute(
                """
                insert into tax_lots (account_id, ticker, qty, cost_basis, acquired_at, external_ref)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (external_ref) do nothing
                """,
                (account_id, ticker, qty, cost_basis, acquired_at, ref),
            )
            inserted += cur.rowcount
            skipped += 1 - cur.rowcount
        conn.commit()
    print(f"seed-lots: {inserted} inserted, {skipped} already present")


def _open_lots(cur, account_id: int, ticker: str) -> list[OpenLot]:
    cur.execute(
        """
        select lot_id, ticker, open_qty, cost_basis, acquired_at
        from lot_open_qty
        where account_id = %s and ticker = %s and open_qty > 0
        """,
        (account_id, ticker),
    )
    return [OpenLot(*row_to_lot(row)) for row in cur.fetchall()]


def row_to_lot(row) -> tuple:
    lot_id, ticker, open_qty, cost_basis, acquired_at = row
    return lot_id, ticker, float(open_qty), float(cost_basis), acquired_at


def _ingest_activity_row(cur, account_id: int, row: ActivityRow, ref: str) -> str:
    if row.kind in ("buy", "reinvest"):
        if not row.symbol or row.qty is None or row.price is None:
            return "skipped"
        cur.execute(
            """
            insert into tax_lots (account_id, ticker, qty, cost_basis, acquired_at, drip, external_ref)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (external_ref) do nothing
            """,
            (account_id, row.symbol, row.qty, row.price, row.run_date,
             row.kind == "reinvest", ref),
        )
        return "buy" if cur.rowcount else "duplicate"

    if row.kind == "dividend":
        if row.amount is None:
            return "skipped"
        cur.execute(
            """
            insert into cash_events (account_id, ticker, kind, amount, occurred_at, external_ref)
            values (%s, %s, 'dividend', %s, %s, %s)
            on conflict (external_ref) do nothing
            """,
            (account_id, row.symbol or None, row.amount, row.run_date, ref),
        )
        return "dividend" if cur.rowcount else "duplicate"

    if row.kind == "sell":
        if not row.symbol or row.qty is None or row.price is None:
            return "skipped"
        cur.execute(
            "select 1 from realized_events where external_ref = %s limit 1", (ref,)
        )
        if cur.fetchone():
            return "duplicate"
        slices = match_fifo(_open_lots(cur, account_id, row.symbol), row.qty, row.run_date, row.price)
        for s in slices:
            cur.execute(
                """
                insert into realized_events (lot_id, qty, sold_at, proceeds, gain, term, external_ref)
                values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (s.lot_id, s.qty, s.sold_at, s.proceeds, s.gain, s.term, ref),
            )
        return "sell"

    return "skipped"


def _apply_adjustment(cur, adj, open_qty: float, sold_at: date) -> None:
    """Apply a wash-sale basis increase + holding-period tack to a replacement lot.

    Full-lot match adjusts in place; partial match splits the lot so only the
    matched shares carry the adjusted basis.
    """
    note = (
        f"wash sale {sold_at}: +{adj.basis_increase_per_share:.4f}/share basis, "
        f"holding period tacked to {adj.tacked_acquired_at}"
    )
    if adj.qty_matched >= open_qty - 1e-9:
        cur.execute(
            """
            update tax_lots
            set cost_basis = cost_basis + %s, acquired_at = %s, wash_sale_adjusted = true
            where id = %s
            """,
            (adj.basis_increase_per_share, adj.tacked_acquired_at, adj.replacement_lot_id),
        )
        target = adj.replacement_lot_id
    else:
        cur.execute(
            "update tax_lots set qty = qty - %s where id = %s",
            (adj.qty_matched, adj.replacement_lot_id),
        )
        cur.execute(
            """
            insert into tax_lots (account_id, ticker, qty, cost_basis, acquired_at,
                                  drip, wash_sale_adjusted, external_ref)
            select account_id, ticker, %s, cost_basis + %s, %s, drip, true, %s
            from tax_lots where id = %s
            returning id
            """,
            (adj.qty_matched, adj.basis_increase_per_share, adj.tacked_acquired_at,
             f"ws:{adj.replacement_lot_id}:{sold_at}:{_ref(adj.qty_matched, adj.basis_increase_per_share)}",
             adj.replacement_lot_id),
        )
        target = cur.fetchone()[0]
    cur.execute(
        """
        insert into lot_adjustments (lot_id, kind, ratio, note)
        values (%s, 'correction', null, %s)
        """,
        (target, note),
    )


def wash_sale_scan(cur) -> dict:
    """Flag unprocessed loss sales that §1091 catches and adjust replacement lots.

    Runs after activity ingestion so buys later in the same file (the forward
    30-day window) are already in the DB.
    """
    cur.execute(
        """
        select re.id, re.lot_id, re.qty, re.sold_at, re.gain, l.ticker, l.acquired_at
        from realized_events re
        join tax_lots l on l.id = re.lot_id
        where re.wash_sale = false and re.gain < 0
        order by re.sold_at
        """
    )
    groups: dict[tuple, list] = {}
    for row in cur.fetchall():
        groups.setdefault((row[5], row[3]), []).append(row)

    totals = {"sales_flagged": 0, "disallowed": 0.0, "permanent": 0.0}
    for (ticker, sold_at), rows in groups.items():
        slices = [
            LossSlice(source_lot_id=lot_id, qty=float(qty),
                      loss_per_share=-float(gain) / float(qty), original_acquired_at=acq)
            for _id, lot_id, qty, _sold, gain, _t, acq in rows
        ]
        start, end = wash_sale_window(sold_at)
        cur.execute(
            """
            select lo.lot_id, lo.open_qty, lo.acquired_at, a.tax_type
            from lot_open_qty lo
            join tax_lots l on l.id = lo.lot_id
            join accounts a on a.id = lo.account_id
            where lo.ticker = %s and lo.open_qty > 0
              and l.wash_sale_adjusted = false
              and lo.acquired_at between %s and %s
            """,
            (ticker, start, end),
        )
        buys = [
            ReplacementBuy(lot_id=r[0], qty_available=float(r[1]), acquired_at=r[2], tax_type=r[3])
            for r in cur.fetchall()
        ]
        open_qty = {b.lot_id: b.qty_available for b in buys}

        outcome = evaluate_wash_sale(slices, buys, sold_at)
        if not outcome.triggered:
            continue
        cur.execute(
            "update realized_events set wash_sale = true where id = any(%s)",
            ([r[0] for r in rows],),
        )
        for adj in outcome.adjustments:
            _apply_adjustment(cur, adj, open_qty[adj.replacement_lot_id], sold_at)
        totals["sales_flagged"] += 1
        totals["disallowed"] += outcome.disallowed_loss
        totals["permanent"] += outcome.permanently_lost

    return totals


def cmd_wash_scan(args) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        totals = wash_sale_scan(cur)
        conn.commit()
    _print_wash_totals(totals)


def _print_wash_totals(totals: dict) -> None:
    if totals["sales_flagged"]:
        print(
            f"⚠ wash sales: {totals['sales_flagged']} loss sale(s) flagged, "
            f"${totals['disallowed']:.2f} disallowed"
            + (f", ${totals['permanent']:.2f} PERMANENTLY lost (IRA repurchase)"
               if totals["permanent"] else "")
        )
    else:
        print("wash sales: none detected")


def cmd_activity(args) -> None:
    rows = parse_activity_csv(Path(args.csv).read_text(encoding="utf-8-sig"))
    # Chronological order matters: a buy must exist before the sell that consumes it.
    rows.sort(key=lambda r: r.run_date)
    counts: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    with get_conn() as conn, conn.cursor() as cur:
        for row in rows:
            account_name = args.account or row.account
            if not account_name:
                raise SystemExit("CSV has no Account column — pass --account")
            account_id = _account_id(cur, account_name)
            base = _ref(row.run_date, account_name, row.action_raw, row.symbol,
                        row.qty, row.price, row.amount)
            seen[base] += 1  # identical rows (same day, same trade) stay distinct
            counts[_ingest_activity_row(cur, account_id, row, f"{base}:{seen[base]}")] += 1
        totals = wash_sale_scan(cur)
        conn.commit()
    print(f"activity: {dict(counts)}")
    _print_wash_totals(totals)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingest_portfolio")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("account-add", help="create or update an account")
    p.add_argument("--name", required=True)
    p.add_argument("--broker", default="fidelity")
    p.add_argument("--tax-type", required=True, choices=["taxable", "ira", "other"])
    p.add_argument("--owner", default="self", choices=["self", "spouse"])
    p.set_defaults(func=cmd_account_add)

    p = sub.add_parser("seed-lots", help="one-time manual lot seeding from CSV")
    p.add_argument("csv")
    p.set_defaults(func=cmd_seed_lots)

    p = sub.add_parser("activity", help="ingest a Fidelity Activity/History CSV")
    p.add_argument("csv")
    p.add_argument("--account", help="account name override when CSV lacks one")
    p.set_defaults(func=cmd_activity)

    p = sub.add_parser("wash-scan", help="re-run wash-sale detection on recorded loss sales")
    p.set_defaults(func=cmd_wash_scan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
