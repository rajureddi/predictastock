"""Surveillance is point-in-time, and an undated headline is not a historical headline."""
from datetime import date

from app.services.market_events import parse_surveillance_csv, parse_results_csv
from app.services.news_sentiment import headline_is_known_on
from app.services.prediction_engine import apply_trade_hygiene, _calibration_rank_term


ASM_SAMPLE = """SYMBOL ,COMPANY ,ISIN ,ASM Stage,TIMESTAMP
--------------------,--------------------,--------------------,----,-----------
IDEA ,Vodafone Idea Limited ,INE669E01016 ,I ,03-Nov-2026
"""

GSM_SAMPLE = '''"SR. NO","SYMBOL","COMPANY NAME","ISIN","GSM STAGE"
"1","ALPSINDUS","Alps Industries Limited","INE093B01015","I"
'''


def test_surveillance_parser_reads_asm_and_gsm():
    asm = parse_surveillance_csv(ASM_SAMPLE, "ASM_LONG")
    assert asm == [{
        "symbol": "IDEA",
        "list_name": "ASM_LONG",
        "stage": "I",
        "observed_on": "2026-11-03",
        "company": "Vodafone Idea Limited",
    }]
    gsm = parse_surveillance_csv(GSM_SAMPLE, "GSM")
    assert gsm[0]["symbol"] == "ALPSINDUS"
    assert gsm[0]["observed_on"] == date.today().isoformat()


def test_results_parser_keeps_the_day_the_file_was_seen():
    text = "Symbol,Company,Purpose,Board Meeting Date\nTCS,Tata Consultancy,Results,12-Nov-2026\n"
    rows = parse_results_csv(text, date(2026, 11, 3))
    assert rows[0]["symbol"] == "TCS"
    assert rows[0]["event_date"] == "2026-11-12"
    assert rows[0]["announced_on"] == "2026-11-03"


def test_surveillance_blocks_only_after_the_list_was_observed():
    surveillance = {"IDEA": [{"list_name": "ASM_LONG", "stage": "I", "observed_on": date(2026, 11, 3)}]}
    later = apply_trade_hygiene(
        {"symbol": "IDEA", "as_of_date": "2026-11-03"},
        surveillance=surveillance,
    )
    earlier = apply_trade_hygiene(
        {"symbol": "IDEA", "as_of_date": "2025-12-01"},
        surveillance=surveillance,
    )
    assert later["trade_block"] == "surveillance ASM_LONG"
    assert "trade_block" not in earlier


def test_results_block_only_when_the_date_was_already_known():
    events = {"TCS": [{
        "event_type": "RESULTS",
        "event_date": date(2026, 11, 12),
        "announced_on": date(2026, 11, 3),
    }]}
    live = apply_trade_hygiene({"symbol": "TCS", "as_of_date": "2026-11-04"}, exchange_events=events)
    old = apply_trade_hygiene({"symbol": "TCS", "as_of_date": "2026-06-01"}, exchange_events=events)
    assert live["trade_block"] == "results inside the hold"
    assert "trade_block" not in old


def test_undated_headline_is_not_known_on_an_old_monday():
    monday = date(2025, 12, 1)
    assert headline_is_known_on("", monday) is False
    assert headline_is_known_on("not-a-date", monday) is False
    assert headline_is_known_on("Mon, 01 Dec 2025 10:00:00 GMT", monday) is True
    assert headline_is_known_on("Tue, 02 Dec 2025 10:00:00 GMT", monday) is False


def test_ranker_stays_idle_without_a_passing_calibration(monkeypatch):
    monkeypatch.setattr(
        "app.services.prediction_engine._load_rank_calibration",
        lambda: None,
    )
    assert _calibration_rank_term({"rs_20d": 1.0}) == 0.0
