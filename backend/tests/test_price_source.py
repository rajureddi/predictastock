"""The desk shows the exchange print, not a feed that stopped one session early."""
from datetime import date

import pandas as pd

from app.services import market_data


def _frame(rows):
    index = pd.to_datetime([row[0] for row in rows])
    return pd.DataFrame(
        {
            "Open": [row[1] for row in rows],
            "High": [row[2] for row in rows],
            "Low": [row[3] for row in rows],
            "Close": [row[4] for row in rows],
            "Volume": [1000 for _ in rows],
        },
        index=index,
    )


def test_exchange_close_replaces_a_blank_live_bar(monkeypatch):
    official = _frame([
        ("2026-11-04", 1140, 1155, 1120, 1128.2),
        ("2026-11-05", 1130, 1173, 1126, 1167.4),
    ])
    live = _frame([
        ("2026-11-04", 1140, 1155, 1120, 1128.2),
        ("2026-11-05", 1130, 1173, 1126, float("nan")),
    ])
    monkeypatch.setattr(market_data, "_local_history_fallback", lambda *args, **kwargs: official)
    monkeypatch.setattr(market_data, "_official_print_is_current", lambda frame: False)
    monkeypatch.setattr(market_data, "_download_yahoo_history", lambda *args, **kwargs: live)

    frame, source = market_data.load_price_history("INFY", period="3mo", yahoo_ticker="INFY.NS")

    assert source == "NSE bhavcopy"
    assert float(frame["Close"].iloc[-1]) == 1167.4
    assert frame.index[-1].date() == date(2026, 11, 5)


def test_a_later_completed_live_session_is_appended(monkeypatch):
    official = _frame([("2026-11-04", 1140, 1155, 1120, 1128.2)])
    live = _frame([
        ("2026-11-04", 1100, 1110, 1090, 1100.0),
        ("2026-11-05", 1130, 1173, 1126, 1167.4),
    ])
    monkeypatch.setattr(market_data, "_local_history_fallback", lambda *args, **kwargs: official)
    monkeypatch.setattr(market_data, "_official_print_is_current", lambda frame: False)
    monkeypatch.setattr(market_data, "_download_yahoo_history", lambda *args, **kwargs: live)

    frame, source = market_data.load_price_history("INFY", period="5d", yahoo_ticker="INFY.NS")

    assert source == "NSE bhavcopy plus later live session"
    assert float(frame["Close"].iloc[-2]) == 1128.2
    assert float(frame["Close"].iloc[-1]) == 1167.4


def test_current_exchange_file_is_not_replaced_by_the_feed(monkeypatch):
    official = _frame([("2026-11-05", 1130, 1173, 1126, 1167.4)])
    called = []
    monkeypatch.setattr(market_data, "_local_history_fallback", lambda *args, **kwargs: official)
    monkeypatch.setattr(market_data, "_official_print_is_current", lambda frame: True)
    monkeypatch.setattr(
        market_data,
        "_download_yahoo_history",
        lambda *args, **kwargs: called.append(args) or official,
    )

    frame, source = market_data.load_price_history("INFY", period="3mo", yahoo_ticker="INFY.NS")

    assert called == []
    assert source == "NSE bhavcopy"
    assert float(frame["Close"].iloc[-1]) == 1167.4
