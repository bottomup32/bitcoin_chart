"""Parser for Fidelity's Activity/History CSV export. Pure, no I/O.

Fidelity's export wraps the table in preamble lines and a legal-disclaimer
footer, and column names drift over time, so the parser is deliberately
forgiving: it locates the header row itself, matches columns by fuzzy name,
and stops at the first non-data row after the table (PLAN.md §1 [2]).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class ActivityRow:
    run_date: date
    account: str
    action_raw: str
    kind: str  # buy | sell | reinvest | dividend | other
    symbol: str
    qty: float | None  # positive share count where applicable
    price: float | None
    amount: float | None


def _classify(action: str) -> str:
    a = action.upper()
    if "REINVESTMENT" in a:
        return "reinvest"
    if "YOU BOUGHT" in a or a.startswith("BOUGHT"):
        return "buy"
    if "YOU SOLD" in a or a.startswith("SOLD"):
        return "sell"
    if "DIVIDEND" in a:
        return "dividend"
    return "other"


def _parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace("$", "").replace(",", "")
    if cleaned in ("", "-", "--"):
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


def _find_column(fieldnames: list[str], *keywords: str) -> str | None:
    """First column whose normalized name contains all keywords."""
    for name in fieldnames:
        normalized = re.sub(r"[^a-z]", " ", name.lower())
        if all(kw in normalized for kw in keywords):
            return name
    return None


def parse_activity_csv(text: str) -> list[ActivityRow]:
    lines = text.lstrip("﻿").splitlines()

    header_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if "run date" in line.lower() and "," in line
        ),
        None,
    )
    if header_idx is None:
        raise ValueError("could not find a 'Run Date' header row — is this an Activity CSV?")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    fields = reader.fieldnames or []
    col_date = _find_column(fields, "run", "date")
    col_account = _find_column(fields, "account")
    col_action = _find_column(fields, "action")
    col_symbol = _find_column(fields, "symbol")
    col_qty = _find_column(fields, "quantity")
    col_price = _find_column(fields, "price")
    col_amount = _find_column(fields, "amount")
    if not col_date or not col_action:
        raise ValueError("Activity CSV is missing 'Run Date' or 'Action' columns")

    rows: list[ActivityRow] = []
    for raw in reader:
        run_date = _parse_date(raw.get(col_date) or "")
        if run_date is None:
            break  # footer/disclaimer reached
        action = (raw.get(col_action) or "").strip()
        qty = _parse_number(raw.get(col_qty)) if col_qty else None
        rows.append(
            ActivityRow(
                run_date=run_date,
                account=(raw.get(col_account) or "").strip() if col_account else "",
                action_raw=action,
                kind=_classify(action),
                symbol=(raw.get(col_symbol) or "").strip().upper() if col_symbol else "",
                qty=abs(qty) if qty is not None else None,
                price=_parse_number(raw.get(col_price)) if col_price else None,
                amount=_parse_number(raw.get(col_amount)) if col_amount else None,
            )
        )
    return rows
