"""
NSE + BSE End-of-Day Store
Builds the full-market price panel from the official exchange bhavcopy archives,
so the daily scan reads local bars instead of calling Yahoo once per stock.

- NSE: sec_bhavdata_full_DDMMYYYY.csv (OHLC, volume, turnover, delivery)
- BSE: BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV (UDiFF format, OHLC, volume, turnover, ISIN)
- A company listed on both exchanges is stored once, under its NSE symbol.
- Raw prices are stored as published. Split/bonus back-adjustment happens at read
  time in market_data.get_historical_market_bars using the exchange's PREV_CLOSE.
"""
import io
import os
import ssl
import time
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from app.database import get_db_connection
from app.data.nse_calendar import is_trading_day
from app.config import (
    SCAN_EXCHANGES, SCAN_NSE_SERIES, SCAN_BSE_GROUPS,
    SCAN_MIN_TURNOVER_CR, SCAN_MIN_PRICE, SCAN_MAX_UNIVERSE,
)

logger = logging.getLogger(__name__)

NSE_EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST"}
BSE_EQUITY_GROUPS = {"A", "B", "T", "X", "XT", "Z", "ZP", "M", "MT", "MS", "P", "W"}
ETF_NAME_MARKERS = ("ETF", "BEES", "LIQUID", "GOLD BOND", "SGB")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/csv,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _bhav_dir(exchange: str) -> str:
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "bhavcopy")
    path = base if exchange == "NSE" else os.path.join(base, "bse")
    os.makedirs(path, exist_ok=True)
    return path


def _file_spec(exchange: str, d: date) -> Tuple[str, str, Dict[str, str]]:
    if exchange == "NSE":
        name = f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
        return name, f"https://archives.nseindia.com/products/content/{name}", _HEADERS
    name = f"BhavCopy_BSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.CSV"
    headers = dict(_HEADERS, Referer="https://www.bseindia.com/")
    return name, f"https://www.bseindia.com/download/BhavCopy/Equity/{name}", headers


NO_SESSION = "NO_SESSION"
_CSV_HEADER_PREFIX = {"NSE": b"SYMBOL", "BSE": b"TradDt"}


def _is_bhavcopy_csv(exchange: str, data: bytes) -> bool:
    return len(data) > 1000 and data.lstrip(b"\xef\xbb\xbf").startswith(_CSV_HEADER_PREFIX[exchange])


def download_bhavcopy(exchange: str, d: date, force: bool = False) -> Optional[str]:
    """Local path of one session's bhavcopy, downloading it if needed.

    Returns NO_SESSION when the exchange confirms there is no file (404, or BSE's
    habit of serving its homepage for holidays) and None on transient failure.
    """
    name, url, headers = _file_spec(exchange, d)
    local_path = os.path.join(_bhav_dir(exchange), name)
    if not force and os.path.exists(local_path):
        with open(local_path, "rb") as f:
            if _is_bhavcopy_csv(exchange, f.read(2048)):
                return local_path
        os.remove(local_path)
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
                data = resp.read()
            if not _is_bhavcopy_csv(exchange, data):
                return NO_SESSION
            with open(local_path, "wb") as f:
                f.write(data)
            return local_path
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return NO_SESSION
            logger.debug(f"{exchange} bhavcopy {d} HTTP {e.code} (attempt {attempt + 1})")
        except Exception as e:
            logger.debug(f"{exchange} bhavcopy {d} failed (attempt {attempt + 1}): {e}")
        time.sleep(1.5)
    return None


def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def parse_nse_bhavcopy(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    df["SERIES"] = df["SERIES"].astype(str).str.strip()
    df = df[df["SERIES"].isin(NSE_EQUITY_SERIES)].copy()
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].astype(str).str.strip(),
        "series": df["SERIES"],
        "trading_date": pd.to_datetime(df["DATE1"].astype(str).str.strip(), format="%d-%b-%Y").dt.strftime("%Y-%m-%d"),
        "open": _to_num(df["OPEN_PRICE"]),
        "high": _to_num(df["HIGH_PRICE"]),
        "low": _to_num(df["LOW_PRICE"]),
        "close": _to_num(df["CLOSE_PRICE"]),
        "prev_close": _to_num(df["PREV_CLOSE"]),
        "volume": _to_num(df["TTL_TRD_QNTY"]).fillna(0),
        "turnover_lacs": _to_num(df["TURNOVER_LACS"]).fillna(0.0),
        "deliv_qty": _to_num(df["DELIV_QTY"]),
        "deliv_per": _to_num(df["DELIV_PER"]),
        "isin": None,
        "name": None,
        "exchange": "NSE",
    })
    return out[out["close"] > 0]


def parse_bse_bhavcopy(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df[df["FinInstrmTp"].str.strip() == "STK"].copy()
    df["SctySrs"] = df["SctySrs"].astype(str).str.strip()
    df = df[df["SctySrs"].isin(BSE_EQUITY_GROUPS)]
    out = pd.DataFrame({
        "symbol": df["TckrSymb"].astype(str).str.strip().str.upper(),
        "series": df["SctySrs"],
        "trading_date": pd.to_datetime(df["TradDt"].str.strip()).dt.strftime("%Y-%m-%d"),
        "open": _to_num(df["OpnPric"]),
        "high": _to_num(df["HghPric"]),
        "low": _to_num(df["LwPric"]),
        "close": _to_num(df["ClsPric"]),
        "prev_close": _to_num(df["PrvsClsgPric"]),
        "volume": _to_num(df["TtlTradgVol"]).fillna(0),
        "turnover_lacs": _to_num(df["TtlTrfVal"]).fillna(0.0) / 1e5,
        "deliv_qty": None,
        "deliv_per": None,
        "isin": df["ISIN"].astype(str).str.strip(),
        "name": df["FinInstrmNm"].astype(str).str.strip(),
        "exchange": "BSE",
        "bse_code": df["FinInstrmId"].astype(str).str.strip(),
    })
    return out[out["close"] > 0]


def _expected_sessions(trading_days: int, end: Optional[date] = None) -> List[date]:
    """Most recent `trading_days` NSE sessions up to `end` (exchanges share one calendar)."""
    cursor_day = end or date.today()
    if datetime.now().hour < 18 and cursor_day == date.today():
        cursor_day -= timedelta(days=1)  # today's files publish in the evening
    sessions: List[date] = []
    while len(sessions) < trading_days:
        nse_local = os.path.join(_bhav_dir("NSE"), f"sec_bhavdata_full_{cursor_day.strftime('%d%m%Y')}.csv")
        if is_trading_day(cursor_day) or os.path.exists(nse_local):
            sessions.append(cursor_day)
        cursor_day -= timedelta(days=1)
    return sorted(sessions)


def _ingested_sessions(cursor, exchange: str) -> Set[str]:
    cursor.execute("SELECT trading_date FROM eod_sessions WHERE exchange = ?", (exchange,))
    return {r["trading_date"] for r in cursor.fetchall()}


def _nifty_by_date(sessions: List[date]) -> Dict[str, Tuple[float, float]]:
    """Optional benchmark context for the walk-forward evaluator. Missing data is left NULL."""
    try:
        import yfinance as yf
        hist = yf.Ticker("^NSEI").history(start=(sessions[0] - timedelta(days=40)).isoformat(),
                                          end=(sessions[-1] + timedelta(days=1)).isoformat())
        hist = hist.dropna(subset=["Close"])
        hist["SMA_20"] = hist["Close"].rolling(20, min_periods=1).mean()
        return {idx.strftime("%Y-%m-%d"): (round(float(r.Close), 2), round(float(r.SMA_20), 2))
                for idx, r in hist.iterrows()}
    except Exception as e:
        logger.warning(f"Nifty context unavailable for EOD sync: {e}")
        return {}


def _ingest_session(cursor, nse_df: Optional[pd.DataFrame], bse_df: Optional[pd.DataFrame],
                    nse_isins: Dict[str, str], nse_names: Dict[str, str],
                    nifty: Dict[str, Tuple[float, float]], now_ts: str) -> Dict[str, int]:
    counts = {"NSE": 0, "BSE": 0}
    frames = []
    nse_symbols: Set[str] = set()
    if nse_df is not None and not nse_df.empty:
        nse_df = nse_df.copy()
        nse_df["isin"] = nse_df["symbol"].map(nse_isins)
        nse_df["name"] = nse_df["symbol"].map(nse_names)
        if bse_df is not None and not bse_df.empty:
            bse_by_symbol = bse_df.drop_duplicates("symbol").set_index("symbol")
            nse_df["name"] = nse_df["name"].fillna(nse_df["symbol"].map(bse_by_symbol["name"]))
            nse_df["isin"] = nse_df["isin"].replace("", None).fillna(nse_df["symbol"].map(bse_by_symbol["isin"]))
        nse_symbols = set(nse_df["symbol"])
        frames.append(nse_df)
    if bse_df is not None and not bse_df.empty:
        known_isins = {i for i in nse_isins.values() if i}
        dup = bse_df["isin"].isin(known_isins) | bse_df["symbol"].isin(nse_symbols) | bse_df["symbol"].isin(nse_isins.keys())
        frames.append(bse_df[~dup])

    for frame in frames:
        trading_date = frame["trading_date"].iloc[0]
        n_close, n_sma = nifty.get(trading_date, (None, None))
        exchange = frame["exchange"].iloc[0]
        source = "NSE_BHAVCOPY" if exchange == "NSE" else "BSE_BHAVCOPY"
        report_date = trading_date.replace("-", "")
        records = []
        listings = []
        for r in frame.itertuples(index=False):
            c = float(r.close)
            o = float(r.open) if pd.notna(r.open) and r.open > 0 else c
            h = float(r.high) if pd.notna(r.high) and r.high > 0 else c
            l = float(r.low) if pd.notna(r.low) and r.low > 0 else c
            dq = float(r.deliv_qty) if r.deliv_qty is not None and pd.notna(r.deliv_qty) else None
            dp = float(r.deliv_per) if r.deliv_per is not None and pd.notna(r.deliv_per) else None
            pc = float(r.prev_close) if pd.notna(r.prev_close) and r.prev_close > 0 else None
            records.append((
                r.symbol, trading_date, o, h, l, c, int(r.volume), c, "RAW_EXCHANGE_PRICE",
                dq, dp, source, report_date, now_ts, "VERIFIED", n_close, n_sma,
                r.isin or "", exchange, r.series, pc, float(r.turnover_lacs),
            ))
            listings.append((
                r.symbol, exchange, r.isin or "", r.name or r.symbol, r.series,
                getattr(r, "bse_code", None), trading_date, now_ts,
            ))
        cursor.executemany("""
        INSERT OR REPLACE INTO historical_market_bars (
            symbol, trading_date, open, high, low, close, volume, adj_close, adjustment_method,
            deliv_qty, deliv_per, delivery_source, report_date, retrieval_timestamp, quality_status,
            nifty50_close, nifty50_sma20, isin, exchange, series, prev_close, turnover_lacs
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        cursor.executemany("""
        INSERT INTO exchange_listings (symbol, exchange, isin, name, series, bse_code, last_trading_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            exchange = excluded.exchange,
            isin = CASE WHEN excluded.isin != '' THEN excluded.isin ELSE exchange_listings.isin END,
            name = CASE WHEN excluded.name != excluded.symbol THEN excluded.name ELSE exchange_listings.name END,
            series = excluded.series,
            bse_code = COALESCE(excluded.bse_code, exchange_listings.bse_code),
            last_trading_date = MAX(excluded.last_trading_date, exchange_listings.last_trading_date),
            updated_at = excluded.updated_at
        WHERE excluded.exchange = 'NSE' OR exchange_listings.exchange = 'BSE'
        """, listings)
        cursor.execute(
            "INSERT OR REPLACE INTO eod_sessions (exchange, trading_date, row_count, ingested_at) VALUES (?, ?, ?, ?)",
            (exchange, trading_date, len(records), now_ts),
        )
        counts[exchange] += len(records)
    return counts


def backfill_older_sessions(trading_days: Optional[int] = None, max_workers: int = 4) -> Dict[str, Any]:
    """Pull archive sessions past the daily window. The daily scan does not call this.

    NSE and BSE publish the files this store already knows how to read. A two-year
    pull is a few hundred sessions and should be run on its own, not inside a scan.
    """
    from app.config import HISTORY_BACKFILL_SESSIONS
    return sync_eod_store(
        trading_days=trading_days or HISTORY_BACKFILL_SESSIONS,
        max_workers=max_workers,
    )


def sync_eod_store(
    trading_days: int = 260,
    exchanges: Iterable[str] = ("NSE", "BSE"),
    force_download: bool = False,
    max_workers: int = 4,
) -> Dict[str, Any]:
    """Download and ingest the last `trading_days` sessions for NSE and BSE.

    Sessions already recorded in eod_sessions are skipped, so the daily run only
    fetches the newest file per exchange.
    """
    exchanges = [e.upper() for e in exchanges]
    sessions = _expected_sessions(trading_days)
    conn = get_db_connection()
    cursor = conn.cursor()
    done = {ex: (set() if force_download else _ingested_sessions(cursor, ex)) for ex in exchanges}
    pending = [d for d in sessions if any(d.isoformat() not in done[ex] for ex in exchanges)]
    logger.info(f"EOD sync: {len(pending)} of {len(sessions)} sessions need ingestion for {exchanges}.")

    cursor.execute("SELECT symbol, isin, name FROM nse_equities")
    rows = cursor.fetchall()
    nse_isins = {r["symbol"]: (r["isin"] or "") for r in rows}
    nse_names = {r["symbol"]: r["name"] for r in rows}

    nifty = _nifty_by_date(pending) if pending else {}
    totals = {"NSE": 0, "BSE": 0}
    missing: Dict[str, List[str]] = {ex: [] for ex in exchanges}
    now_ts = datetime.now().isoformat()

    def fetch(d: date) -> Tuple[date, Dict[str, Optional[str]]]:
        paths = {}
        for ex in exchanges:
            paths[ex] = None if d.isoformat() in done[ex] else download_bhavcopy(ex, d, force=force_download)
        return d, paths

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for d, paths in pool.map(fetch, pending):
            frames: Dict[str, Optional[pd.DataFrame]] = {"NSE": None, "BSE": None}
            for ex in exchanges:
                if d.isoformat() in done[ex]:
                    continue
                if paths[ex] == NO_SESSION:
                    # Only settled dates are marked as holidays; a recent file may not be published yet.
                    if (date.today() - d).days >= 3:
                        cursor.execute(
                            "INSERT OR REPLACE INTO eod_sessions (exchange, trading_date, row_count, ingested_at) VALUES (?, ?, 0, ?)",
                            (ex, d.isoformat(), now_ts),
                        )
                    else:
                        missing[ex].append(d.isoformat())
                    continue
                if not paths[ex]:
                    missing[ex].append(d.isoformat())
                    continue
                try:
                    frames[ex] = parse_nse_bhavcopy(paths[ex]) if ex == "NSE" else parse_bse_bhavcopy(paths[ex])
                except Exception as e:
                    logger.warning(f"Could not parse {ex} bhavcopy for {d}: {e}")
                    missing[ex].append(d.isoformat())
            # BSE dedupe needs that day's NSE symbols; reuse the stored NSE session if it was ingested earlier.
            if frames["BSE"] is not None and frames["NSE"] is None and "NSE" in exchanges:
                cursor.execute("SELECT symbol FROM historical_market_bars WHERE trading_date = ? AND exchange = 'NSE'", (d.isoformat(),))
                stored_nse = {r["symbol"] for r in cursor.fetchall()}
                frames["BSE"] = frames["BSE"][~frames["BSE"]["symbol"].isin(stored_nse)]
            counts = _ingest_session(cursor, frames["NSE"], frames["BSE"], nse_isins, nse_names, nifty, now_ts)
            conn.commit()
            for ex, n in counts.items():
                totals[ex] += n

    conn.close()
    summary = {
        "status": "COMPLETED",
        "sessions_requested": len(sessions),
        "sessions_ingested": len(pending),
        "bars_inserted": totals,
        "missing_sessions": {ex: m for ex, m in missing.items() if m},
        "coverage": get_eod_store_coverage(),
    }
    logger.info(f"EOD sync complete: {summary['bars_inserted']} bars, missing {summary['missing_sessions']}.")
    return summary


def get_eod_store_coverage() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT exchange, COUNT(*) AS sessions, MIN(trading_date) AS start_date, MAX(trading_date) AS end_date
    FROM eod_sessions WHERE row_count > 0 GROUP BY exchange
    """)
    sessions = {r["exchange"]: dict(r) for r in cursor.fetchall()}
    cursor.execute("SELECT exchange, COUNT(*) AS listings FROM exchange_listings GROUP BY exchange")
    for r in cursor.fetchall():
        sessions.setdefault(r["exchange"], {})["listings"] = r["listings"]
    conn.close()
    return sessions


def get_full_market_universe(
    exchanges: Iterable[str] = SCAN_EXCHANGES,
    nse_series: Iterable[str] = SCAN_NSE_SERIES,
    bse_groups: Iterable[str] = SCAN_BSE_GROUPS,
    min_turnover_cr: float = SCAN_MIN_TURNOVER_CR,
    min_price: float = SCAN_MIN_PRICE,
    max_count: int = SCAN_MAX_UNIVERSE,
    lookback_sessions: int = 20,
    as_of_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Every NSE/BSE equity that traded in the latest session and clears the liquidity floor.

    Liquidity is the average daily turnover over the last `lookback_sessions`, so a
    single spike day cannot pull an illiquid stock into the scan.
    """
    exchanges = {e.upper() for e in exchanges}
    allowed = {"NSE": {s.upper() for s in nse_series}, "BSE": {g.upper() for g in bse_groups}}
    conn = get_db_connection()
    try:
        if as_of_date:
            recent = pd.read_sql_query(
                """SELECT DISTINCT trading_date FROM historical_market_bars
                   WHERE trading_date <= ?
                   ORDER BY trading_date DESC LIMIT ?""",
                conn, params=(str(as_of_date)[:10], lookback_sessions),
            )["trading_date"].tolist()
        else:
            recent = pd.read_sql_query(
                "SELECT DISTINCT trading_date FROM eod_sessions WHERE row_count > 0 ORDER BY trading_date DESC LIMIT ?",
                conn, params=(lookback_sessions,),
            )["trading_date"].tolist()
        if not recent:
            return []
        placeholders = ",".join("?" * len(recent))
        bars = pd.read_sql_query(f"""
            SELECT b.symbol, b.trading_date, b.close, b.turnover_lacs, b.exchange, b.series,
                   COALESCE(l.name, b.symbol) AS name
            FROM historical_market_bars b
            LEFT JOIN exchange_listings l ON l.symbol = b.symbol
            WHERE b.trading_date IN ({placeholders}) AND b.turnover_lacs IS NOT NULL
        """, conn, params=recent)
    finally:
        conn.close()

    if bars.empty:
        return []
    latest_date = max(recent)
    bars = bars.sort_values("trading_date")
    agg = bars.groupby("symbol").agg(
        avg_turnover_lacs=("turnover_lacs", "mean"),
        sessions=("trading_date", "count"),
        last_date=("trading_date", "last"),
        close=("close", "last"),
        exchange=("exchange", "last"),
        series=("series", "last"),
        name=("name", "last"),
    ).reset_index()

    agg = agg[
        (agg["last_date"] == latest_date)
        & (agg["sessions"] >= max(1, len(recent) // 2))
        & (agg["close"] >= min_price)
        & (agg["avg_turnover_lacs"] >= min_turnover_cr * 100.0)
        & agg["exchange"].isin(exchanges)
    ]
    series_upper = agg["series"].astype(str).str.upper()
    agg = agg[
        ((agg["exchange"] == "NSE") & series_upper.isin(allowed["NSE"]))
        | ((agg["exchange"] == "BSE") & series_upper.isin(allowed["BSE"]))
    ]
    upper_names = agg["name"].astype(str).str.upper()
    upper_syms = agg["symbol"].astype(str).str.upper()
    is_fund = upper_syms.str.endswith(("BEES", "ETF", "CASE")) | upper_names.apply(
        lambda n: any(m in n for m in ETF_NAME_MARKERS)
    )
    agg = agg[~is_fund].sort_values("avg_turnover_lacs", ascending=False).head(max_count)

    from app.data.nifty_constituents import get_symbol_info
    universe = []
    for r in agg.itertuples(index=False):
        info = get_symbol_info(r.symbol)
        name = r.name if r.name and r.name != r.symbol else info.get("name", r.symbol)
        universe.append({
            "symbol": r.symbol,
            "name": name,
            "sector": info.get("sector", "Indian Equities"),
            "is_nifty50": info.get("is_nifty50", False),
            "exchange": r.exchange,
            "series": r.series,
            "yahoo_ticker": f"{r.symbol}.{'NS' if r.exchange == 'NSE' else 'BO'}",
            "turnover_lacs": round(float(r.avg_turnover_lacs), 2),
            "close_price": float(r.close),
            "sleeve": "FULL_MARKET",
        })
    logger.info(f"Full-market universe for {latest_date}: {len(universe)} equities "
                f"(NSE {sum(u['exchange'] == 'NSE' for u in universe)}, BSE {sum(u['exchange'] == 'BSE' for u in universe)}).")
    return universe
