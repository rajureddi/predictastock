"""Search must resolve company names to the exchange that actually lists them."""
import pandas as pd

from app.services import listings
from app.services import market_data


def setup_function():
    listings._RESOLVE_CACHE.clear()


def test_nse_symbol_and_company_name_stay_on_nse(monkeypatch):
    def forbid_remote(*_args, **_kwargs):
        raise AssertionError("NSE names that are already in the master must not call Yahoo")

    monkeypatch.setattr(listings, "search_yahoo_equities", forbid_remote)
    by_symbol = listings.resolve_equity("BAJAJ-AUTO", remote=True)
    by_name = listings.resolve_equity("Reliance Industries Ltd", remote=True)

    assert by_symbol["symbol"] == "BAJAJ-AUTO"
    assert by_symbol["yahoo_ticker"] == "BAJAJ-AUTO.NS"
    assert by_name["symbol"] == "RELIANCE"
    assert by_name["exchange"] == "NSE"
    assert by_name["yahoo_ticker"] == "RELIANCE.NS"


def test_bse_legal_name_resolves_to_bse_ticker(monkeypatch):
    def fake_yahoo(query, limit=8):
        return [
            listings._listing("AAYUSH", "AAYUSH WELLNESS LIMITED", "BSE"),
            listings._listing("AAYUSHBULL", "AAYUSH ART AND BULLION LIMITED", "BSE"),
        ]

    monkeypatch.setattr(listings, "search_yahoo_equities", fake_yahoo)
    listing = listings.resolve_equity("AAYUSH ART AND BULLION LIMITED", remote=True)

    assert listing["symbol"] == "AAYUSHBULL"
    assert listing["exchange"] == "BSE"
    assert listing["yahoo_ticker"] == "AAYUSHBULL.BO"


def test_search_ranks_full_legal_name_ahead_of_a_shorter_lookalike(monkeypatch):
    def fake_yahoo(query, limit=8):
        return [
            listings._listing("AAYUSH", "AAYUSH WELLNESS LIMITED", "BSE"),
            listings._listing("AAYUSHBULL", "AAYUSH ART AND BULLION LIMITED", "BSE"),
        ]

    monkeypatch.setattr(listings, "search_yahoo_equities", fake_yahoo)
    rows = listings.search_equities("aayush art and bullion limited")

    assert rows[0]["symbol"] == "AAYUSHBULL"
    assert rows[0]["exchange"] == "BSE"
    assert any(row["symbol"] == "AAYUSH" for row in rows)


def test_yahoo_parser_drops_us_listings():
    payload = {
        "quotes": [
            {
                "symbol": "INFY",
                "exchange": "NYQ",
                "quoteType": "EQUITY",
                "longname": "Infosys Limited",
                "exchDisp": "NYSE",
            },
            {
                "symbol": "INFY.NS",
                "exchange": "NSI",
                "quoteType": "EQUITY",
                "longname": "Infosys Limited",
                "exchDisp": "NSE",
            },
            {
                "symbol": "INFY.BO",
                "exchange": "BSE",
                "quoteType": "EQUITY",
                "longname": "Infosys Limited",
                "exchDisp": "Bombay",
            },
        ]
    }
    rows = listings._parse_yahoo_quotes(payload)
    assert [row["yahoo_ticker"] for row in rows] == ["INFY.NS", "INFY.BO"]


def test_history_uses_the_resolved_bse_ticker_only(monkeypatch):
    seen = []

    def fake_download(ticker, period):
        seen.append(ticker)
        index = pd.date_range("2026-08-03", periods=6, freq="B")
        if ticker != "AAYUSHBULL.BO":
            return pd.DataFrame()
        return pd.DataFrame(
            {"Close": [10, 11, 12, 13, 14, 15], "High": [11, 12, 13, 14, 15, 16], "Low": [9, 10, 11, 12, 13, 14]},
            index=index,
        )

    monkeypatch.setattr(market_data, "_download_yahoo_history", fake_download)
    monkeypatch.setattr(market_data, "_local_history_fallback", lambda *args, **kwargs: pd.DataFrame())
    market_data._STOCK_HISTORY_CACHE.clear()
    frame = market_data.get_stock_history("AAYUSHBULL", period="3mo", yahoo_ticker="AAYUSHBULL.BO")

    assert seen == ["AAYUSHBULL.BO"]
    assert len(frame) == 6
    assert float(frame["Close"].iloc[-1]) == 15


def test_compact_ticker_does_not_absorb_a_different_company(monkeypatch):
    def fake_yahoo(query, limit=8):
        return [listings._listing("AAYUSHBULL", "AAYUSH ART AND BULLION LIMITED", "BSE")]

    monkeypatch.setattr(listings, "search_yahoo_equities", fake_yahoo)
    listing = listings.resolve_equity("AAYUSH", remote=True)

    assert listing["symbol"] == "AAYUSH"
    assert listing["yahoo_ticker"] == "AAYUSH.NS"
