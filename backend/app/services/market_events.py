"""
Exchange surveillance lists and forthcoming events, stored as of the day we saw them.

NSE publishes the long-term ASM, short-term ASM, and GSM files on the public
archive. A snapshot downloaded today must not rewrite a Monday that happened
before that snapshot. Results and split calendars are fetched when the archive
actually serves them; a missing file stays missing.
"""
from __future__ import annotations

import csv
import io
import logging
import ssl
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from app.database import get_db_connection

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/csv,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/",
}
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

SURVEILLANCE_URLS = {
    "ASM_LONG": "https://archives.nseindia.com/invest/content/Long_Term_ASM.csv",
    "ASM_SHORT": "https://archives.nseindia.com/invest/content/Short_Term_ASM.csv",
    "GSM": "https://archives.nseindia.com/invest/content/GSM.csv",
}

# These paths 404 on the public archive as of Nov 2026. They stay in the list so a
# later archive path is picked up without a code change, and a miss is logged.
RESULTS_URLS = (
    "https://nsearchives.nseindia.com/content/corporate/BM_All_ForthcomingResults.csv",
    "https://archives.nseindia.com/content/corporate/BM_All_ForthcomingResults.csv",
    "https://nsearchives.nseindia.com/content/equities/Results.csv",
)
SPLIT_URLS = (
    "https://nsearchives.nseindia.com/content/corporates/CA_ALL_FORTHCOMING_SPLIT.csv",
    "https://archives.nseindia.com/content/corporates/CA_ALL_FORTHCOMING_SPLIT.csv",
    "https://nsearchives.nseindia.com/content/corporates/CA_ALL_FORTHCOMING_BONUS.csv",
    "https://archives.nseindia.com/content/corporates/CA_ALL_FORTHCOMING_BONUS.csv",
)

_DATE_FORMATS = ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y")


def ensure_event_tables() -> None:
    conn = get_db_connection()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS surveillance_snapshots (
            symbol TEXT NOT NULL,
            list_name TEXT NOT NULL,
            stage TEXT,
            observed_on TEXT NOT NULL,
            company TEXT,
            PRIMARY KEY (symbol, list_name, observed_on)
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS exchange_events (
            symbol TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            announced_on TEXT NOT NULL,
            detail TEXT,
            PRIMARY KEY (symbol, event_type, event_date)
        )
        """)
        conn.commit()
    finally:
        conn.close()


def parse_exchange_date(text: str) -> Optional[date]:
    raw = (text or "").strip().strip('"').strip()
    if not raw or set(raw) <= {"-", " "}:
        return None
    titled = raw.title()
    for candidate in (raw, titled):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate[:20], fmt).date()
            except ValueError:
                continue
    return None


def _clean_symbol(value: str) -> str:
    symbol = (value or "").strip().upper().replace(" ", "")
    if not symbol or set(symbol) <= {"-"}:
        return ""
    if len(symbol) > 20:
        return ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-.")
    if any(ch not in allowed for ch in symbol):
        return ""
    return symbol


def _header_index(header: List[str]) -> Dict[str, int]:
    index: Dict[str, int] = {}
    for i, cell in enumerate(header):
        key = "".join(ch for ch in cell.lower() if ch.isalnum())
        if key and key not in index:
            index[key] = i
    return index


def _cell(row: List[str], index: Dict[str, int], *names: str) -> str:
    for name in names:
        pos = index.get(name)
        if pos is not None and pos < len(row):
            return row[pos]
    return ""


def _csv_rows(text: str) -> List[List[str]]:
    sample = text.lstrip("\ufeff")
    return list(csv.reader(io.StringIO(sample)))


def _header_row(rows: List[List[str]]) -> Optional[int]:
    for i, row in enumerate(rows[:8]):
        joined = " ".join(cell.upper() for cell in row)
        if "SYMBOL" in joined:
            return i
    return None


def parse_surveillance_csv(text: str, list_name: str) -> List[Dict[str, Any]]:
    rows = _csv_rows(text)
    header_at = _header_row(rows)
    if header_at is None:
        return []
    index = _header_index(rows[header_at])
    parsed: List[Dict[str, Any]] = []
    seen = set()
    for row in rows[header_at + 1:]:
        symbol = _clean_symbol(_cell(row, index, "symbol"))
        if not symbol:
            continue
        observed = parse_exchange_date(_cell(row, index, "timestamp", "date")) or date.today()
        stage = _cell(row, index, "asmstage", "gsmstage", "stage").strip()
        company = _cell(row, index, "company", "companyname").strip()
        key = (symbol, observed.isoformat())
        if key in seen:
            continue
        seen.add(key)
        parsed.append({
            "symbol": symbol,
            "list_name": list_name,
            "stage": stage,
            "observed_on": observed.isoformat(),
            "company": company,
        })
    return parsed


def parse_results_csv(text: str, announced_on: date) -> List[Dict[str, Any]]:
    rows = _csv_rows(text)
    header_at = _header_row(rows)
    if header_at is None:
        return []
    index = _header_index(rows[header_at])
    date_key = next(
        (name for name in ("boardmeetingdate", "bmdate", "resultdate", "meetingdate", "date") if name in index),
        None,
    )
    if date_key is None:
        return []
    parsed: List[Dict[str, Any]] = []
    for row in rows[header_at + 1:]:
        symbol = _clean_symbol(_cell(row, index, "symbol"))
        event_date = parse_exchange_date(_cell(row, index, date_key))
        if not symbol or event_date is None:
            continue
        parsed.append({
            "symbol": symbol,
            "event_type": "RESULTS",
            "event_date": event_date.isoformat(),
            "announced_on": announced_on.isoformat(),
            "detail": _cell(row, index, "purpose", "company", "companyname").strip(),
        })
    return parsed


def parse_action_csv(text: str, event_type: str, announced_on: date) -> List[Dict[str, Any]]:
    rows = _csv_rows(text)
    header_at = _header_row(rows)
    if header_at is None:
        return []
    index = _header_index(rows[header_at])
    date_key = next(
        (name for name in ("exdate", "exdt", "bcstartdate", "date") if name in index),
        None,
    )
    if date_key is None:
        return []
    parsed: List[Dict[str, Any]] = []
    for row in rows[header_at + 1:]:
        symbol = _clean_symbol(_cell(row, index, "symbol"))
        event_date = parse_exchange_date(_cell(row, index, date_key))
        if not symbol or event_date is None:
            continue
        parsed.append({
            "symbol": symbol,
            "event_type": event_type,
            "event_date": event_date.isoformat(),
            "announced_on": announced_on.isoformat(),
            "detail": _cell(row, index, "purpose", "subject", "company").strip(),
        })
    return parsed


def _download(url: str) -> Optional[str]:
    request = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=25, context=_SSL_CTX) as response:
            payload = response.read()
    except Exception as exc:
        logger.info("Market event file unavailable (%s): %s", getattr(exc, "code", type(exc).__name__), url)
        return None
    if not payload or payload[:1] in (b"<", b"{"):
        logger.info("Market event file was not a CSV: %s", url)
        return None
    return payload.decode("utf-8", errors="replace")


def _store_surveillance(list_name: str, rows: Iterable[Dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    observed = sorted({row["observed_on"] for row in rows})
    conn = get_db_connection()
    try:
        for stamp in observed:
            conn.execute(
                "DELETE FROM surveillance_snapshots WHERE list_name = ? AND observed_on = ?",
                (list_name, stamp),
            )
        conn.executemany(
            """
            INSERT OR REPLACE INTO surveillance_snapshots
                (symbol, list_name, stage, observed_on, company)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(row["symbol"], row["list_name"], row["stage"], row["observed_on"], row["company"]) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _store_events(rows: Iterable[Dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    conn = get_db_connection()
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO exchange_events
                (symbol, event_type, event_date, announced_on, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(row["symbol"], row["event_type"], row["event_date"], row["announced_on"], row["detail"]) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def sync_market_events() -> Dict[str, Any]:
    """Download today's ASM and GSM lists. These three archive files return a CSV."""
    ensure_event_tables()
    counts: Dict[str, Any] = {}
    for list_name, url in SURVEILLANCE_URLS.items():
        text = _download(url)
        counts[list_name] = _store_surveillance(list_name, parse_surveillance_csv(text, list_name)) if text else 0
    logger.info("Surveillance lists synced: %s", counts)
    return counts


def sync_forthcoming_calendars() -> Dict[str, Any]:
    """Try the public results and split files. As of Nov 2026 those paths return 404.

    Kept off the live scan so a missing calendar does not stall the desk. A file
    that does arrive is stored with announced_on = today, so older Mondays stay untouched.
    """
    ensure_event_tables()
    announced = date.today()
    results: List[Dict[str, Any]] = []
    for url in RESULTS_URLS:
        text = _download(url)
        if not text:
            continue
        results = parse_results_csv(text, announced)
        if results:
            break
    actions: List[Dict[str, Any]] = []
    for url in SPLIT_URLS:
        text = _download(url)
        if not text:
            continue
        kind = "BONUS" if "BONUS" in url.upper() else "SPLIT"
        actions.extend(parse_action_csv(text, kind, announced))
    counts = {
        "RESULTS": _store_events(results),
        "CORPORATE_ACTIONS": _store_events(actions),
    }
    logger.info("Forthcoming calendars: %s", counts)
    return counts


def load_surveillance() -> Dict[str, List[Dict[str, Any]]]:
    ensure_event_tables()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT symbol, list_name, stage, observed_on FROM surveillance_snapshots"
        ).fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    booked: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        observed = parse_exchange_date(str(row["observed_on"]))
        if observed is None:
            continue
        booked.setdefault(row["symbol"], []).append({
            "list_name": row["list_name"],
            "stage": row["stage"],
            "observed_on": observed,
        })
    return booked


def load_exchange_events() -> Dict[str, List[Dict[str, Any]]]:
    ensure_event_tables()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT symbol, event_type, event_date, announced_on, detail FROM exchange_events"
        ).fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    booked: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        event_date = parse_exchange_date(str(row["event_date"]))
        announced = parse_exchange_date(str(row["announced_on"]))
        if event_date is None or announced is None:
            continue
        booked.setdefault(row["symbol"], []).append({
            "event_type": row["event_type"],
            "event_date": event_date,
            "announced_on": announced,
            "detail": row["detail"],
        })
    return booked
