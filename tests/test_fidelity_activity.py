from datetime import date

import pytest

from adapters.fidelity_activity import parse_activity_csv

SAMPLE = """\


Brokerage services are provided by Fidelity Brokerage Services LLC

Run Date,Account,Action,Symbol,Description,Type,Quantity,Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date
01/15/2026,Individual X12345678, YOU BOUGHT             AAPL,AAPL,APPLE INC,Cash,10,185.50,,,,(1855.00),01/16/2026
02/03/2026,Individual X12345678, DIVIDEND RECEIVED,AAPL,APPLE INC,Cash,,,,,,"2.40",
02/03/2026,Individual X12345678, REINVESTMENT,AAPL,APPLE INC,Cash,0.0129,186.05,,,,-2.40,
03/10/2026,Individual X12345678, YOU SOLD              AAPL,AAPL,APPLE INC,Cash,-4,"190.00",,,,760.00,03/11/2026

"The data and information in this spreadsheet is provided to you..."
Date downloaded 03/12/2026
"""


def test_parses_past_preamble_and_stops_at_footer():
    rows = parse_activity_csv(SAMPLE)
    assert len(rows) == 4
    assert all(r.account == "Individual X12345678" for r in rows)


def test_classification_and_values():
    buy, dividend, reinvest, sell = parse_activity_csv(SAMPLE)

    assert buy.kind == "buy"
    assert buy.run_date == date(2026, 1, 15)
    assert buy.symbol == "AAPL"
    assert buy.qty == pytest.approx(10)
    assert buy.price == pytest.approx(185.50)
    assert buy.amount == pytest.approx(-1855.00)  # accounting parentheses = negative

    assert dividend.kind == "dividend"
    assert dividend.amount == pytest.approx(2.40)

    assert reinvest.kind == "reinvest"
    assert reinvest.qty == pytest.approx(0.0129)

    assert sell.kind == "sell"
    assert sell.qty == pytest.approx(4)  # sign stripped
    assert sell.price == pytest.approx(190.00)  # quoted number


def test_missing_header_raises():
    with pytest.raises(ValueError):
        parse_activity_csv("just,some,random\nrows,without,headers\n")


def test_bom_and_iso_dates_tolerated():
    text = "﻿Run Date,Action,Symbol,Quantity,Price ($),Amount ($)\n" \
           "2026-01-15, YOU BOUGHT MSFT,MSFT,5,400.00,-2000.00\n"
    rows = parse_activity_csv(text)
    assert rows[0].run_date == date(2026, 1, 15)
    assert rows[0].kind == "buy"
    assert rows[0].symbol == "MSFT"
