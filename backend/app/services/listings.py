"""
Resolve Indian equity searches to a tradable NSE or BSE listing.

The desk used to treat whatever was typed — including a legal company name —
as an NSE Yahoo ticker (`NAME.NS`). That misses BSE-only companies and any
name that is not itself the ticker. Local NSE masters are checked first.
Yahoo's public search is used only when the typed text is not already an
NSE symbol prefix, and US listings such as the INFY ADR are discarded.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from app.data.nifty_constituents import FULL_NSE_UNIVERSE, SYMBOL_MAP, get_symbol_info

logger = logging.getLogger(__name__)

_NAME_STOPWORDS = {
    "LIMITED", "LTD", "PRIVATE", "PVT", "COMPANY", "CO", "THE", "OF", "AND", "INDIA",
}
_COMPACT_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&._-]{0,24}$")
_RESOLVE_CACHE: Dict[str, Dict[str, Any]] = {}


def _tokens(value: str) -> List[str]:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", (value or "").upper())
    return [part for part in cleaned.split() if part not in _NAME_STOPWORDS and len(part) > 1]


def _name_score(query: str, name: str) -> float:
    query_tokens = _tokens(query)
    name_tokens = _tokens(name)
    if not query_tokens or not name_tokens:
        return 0.0
    overlap = len(set(query_tokens) & set(name_tokens))
    if overlap == 0:
        return 0.0
    recall = overlap / len(set(query_tokens))
    precision = overlap / len(set(name_tokens))
    return round((0.7 * recall) + (0.3 * precision), 4)


def _is_compact_symbol(value: str) -> bool:
    text = (value or "").upper().strip()
    return bool(text) and " " not in text and bool(_COMPACT_SYMBOL.match(text))


def _strip_exchange_suffix(value: str) -> str:
    text = (value or "").upper().strip()
    text = text.split("•")[0].strip()
    for suffix in (".NS", ".BO"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def _listing(
    symbol: str,
    name: str,
    exchange: str,
    sector: str = "Indian Equities",
    series: str = "EQ",
) -> Dict[str, Any]:
    exchange_name = "BSE" if exchange.upper() == "BSE" else "NSE"
    clean_symbol = _strip_exchange_suffix(symbol)
    suffix = "BO" if exchange_name == "BSE" else "NS"
    return {
        "symbol": clean_symbol,
        "name": (name or clean_symbol).strip(),
        "sector": sector or "Indian Equities",
        "exchange": exchange_name,
        "yahoo_ticker": f"{clean_symbol}.{suffix}",
        "series": series or "EQ",
    }


def _from_local(item: Dict[str, Any]) -> Dict[str, Any]:
    return _listing(
        symbol=item["symbol"],
        name=item.get("name") or item["symbol"],
        exchange="NSE",
        sector=item.get("sector") or "Indian Equities",
        series=item.get("series") or "EQ",
    )


def remember_listing(listing: Dict[str, Any]) -> Dict[str, Any]:
    """Cache a resolved listing by symbol, exchange, and normalized name.

    A symbol that exists on the NSE master always keeps the NSE listing on the
    bare-symbol key. A BSE quote for INFY must not replace INFY.NS.
    """
    symbol_key = f"{listing['symbol']}|{listing['exchange']}"
    _RESOLVE_CACHE[symbol_key] = listing
    bare_key = f"{listing['symbol']}|"
    if listing["symbol"] in SYMBOL_MAP:
        _RESOLVE_CACHE[bare_key] = _from_local(SYMBOL_MAP[listing["symbol"]])
    else:
        existing = _RESOLVE_CACHE.get(bare_key)
        if not existing or (existing.get("exchange") != "NSE" and listing["exchange"] == "NSE"):
            _RESOLVE_CACHE[bare_key] = listing
    name_key = "NAME|" + " ".join(_tokens(listing.get("name", "")))
    if name_key != "NAME|":
        current = _RESOLVE_CACHE.get(name_key)
        if not current or (current.get("exchange") != "NSE" and listing["exchange"] == "NSE"):
            _RESOLVE_CACHE[name_key] = listing
        elif current.get("exchange") == listing["exchange"]:
            _RESOLVE_CACHE[name_key] = listing
    return listing


def _search_local(query: str, limit: int) -> List[Dict[str, Any]]:
    needle = query.strip().upper()
    if not needle:
        return [_from_local(item) for item in FULL_NSE_UNIVERSE[:limit]]

    exact: List[Dict[str, Any]] = []
    prefix: List[Dict[str, Any]] = []
    contains_symbol: List[Dict[str, Any]] = []
    contains_name: List[Dict[str, Any]] = []
    for item in FULL_NSE_UNIVERSE:
        symbol = item["symbol"]
        name = (item.get("name") or "").upper()
        row = _from_local(item)
        if symbol == needle:
            exact.append(row)
        elif symbol.startswith(needle):
            prefix.append(row)
        elif needle in symbol:
            contains_symbol.append(row)
        elif needle in name:
            contains_name.append(row)

    if not exact and not prefix and " " in needle:
        scored = []
        for item in FULL_NSE_UNIVERSE:
            score = _name_score(needle, item.get("name") or "")
            if score >= 0.55:
                scored.append((score, _from_local(item)))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        contains_name = [row for _, row in scored[:limit]]

    merged: List[Dict[str, Any]] = []
    seen = set()
    for row in exact + prefix + contains_symbol + contains_name:
        key = (row["symbol"], row["exchange"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged


def _parse_yahoo_quotes(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    listings: List[Dict[str, Any]] = []
    seen = set()
    for quote in payload.get("quotes") or []:
        if (quote.get("quoteType") or "EQUITY").upper() != "EQUITY":
            continue
        raw_symbol = (quote.get("symbol") or "").upper().strip()
        exchange_code = (quote.get("exchange") or "").upper()
        exchange_label = (quote.get("exchDisp") or "").upper()
        if raw_symbol.endswith(".NS") or exchange_code in {"NSI", "NSE"}:
            exchange_name = "NSE"
            base = raw_symbol[:-3] if raw_symbol.endswith(".NS") else raw_symbol
        elif raw_symbol.endswith(".BO") or exchange_code in {"BSE", "BOM"} or "BOMBAY" in exchange_label:
            exchange_name = "BSE"
            base = raw_symbol[:-3] if raw_symbol.endswith(".BO") else raw_symbol
        else:
            continue
        if not _is_compact_symbol(base):
            continue
        key = (base, exchange_name)
        if key in seen:
            continue
        seen.add(key)
        name = quote.get("longname") or quote.get("shortname") or base
        sector = quote.get("sectorDisp") or quote.get("industryDisp") or "Indian Equities"
        listings.append(_listing(base, name, exchange_name, sector=sector))
    return listings


def search_yahoo_equities(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Search Yahoo Finance for NSE (.NS) and BSE (.BO) equities. Never raises."""
    text = (query or "").strip()
    if len(text) < 2:
        return []
    params = urllib.parse.urlencode({
        "q": text,
        "quotesCount": str(max(limit, 8)),
        "newsCount": "0",
        "enableFuzzyQuery": "false",
        "lang": "en-IN",
        "region": "IN",
    })
    hosts = (
        "https://query2.finance.yahoo.com/v1/finance/search",
        "https://query1.finance.yahoo.com/v1/finance/search",
    )
    payload = None
    last_error: Optional[Exception] = None
    for host in hosts:
        request = urllib.request.Request(
            f"{host}?{params}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            break
        except Exception as exc:
            last_error = exc
            logger.warning("Equity search lookup failed for %r via %s: %s", text, host, exc)
    if not isinstance(payload, dict):
        logger.warning("Equity search lookup failed for %r: %s", text, last_error)
        return []
    hits = _parse_yahoo_quotes(payload)
    hits.sort(key=lambda row: _name_score(text, row["name"]), reverse=True)
    for row in hits:
        remember_listing(row)
    return hits[:limit]


def search_equities(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Rank NSE master matches, then add BSE and other Indian listings Yahoo knows
    when the query is a company name or not an NSE ticker prefix.
    """
    text = (query or "").strip()
    local = _search_local(text, limit=limit)
    if len(text) < 2:
        return local[:limit]

    upper = text.upper()
    has_prefix = any(row["symbol"].startswith(upper) for row in local[:8])
    need_remote = (" " in text) or not has_prefix
    remote: List[Dict[str, Any]] = []
    if need_remote:
        remote = search_yahoo_equities(text, limit=8)
        remote.sort(key=lambda row: _name_score(text, row["name"]), reverse=True)

    merged: List[Dict[str, Any]] = []
    seen = set()
    for row in local + remote:
        key = (row["symbol"], row["exchange"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged


def _unique_name_match(query: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    scored = [( _name_score(query, row["name"]), row) for row in rows]
    scored = [pair for pair in scored if pair[0] >= 0.72]
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    # 1.0 means the query and the company name are the same words. A near
    # namesake such as "Reliance Chemotex Industries" must not block it.
    if best_score >= 0.999 and second < 0.999:
        return best
    if best_score >= 0.92 and (best_score - second) >= 0.12:
        return best
    if len(scored) == 1 and best_score >= 0.8:
        return best
    return None


def resolve_equity(query: str, exchange: str = "", remote: bool = True) -> Optional[Dict[str, Any]]:
    """
    Map a ticker or company name to one listing.

    Compact tickers that already exist on the NSE master never touch the network.
    A company name resolves only when one listing is a clear name match, so a
    short fragment cannot silently select a different company.
    """
    exchange_hint = (exchange or "").upper().strip()
    if exchange_hint not in {"NSE", "BSE"}:
        exchange_hint = ""
    compact = _strip_exchange_suffix(query)
    if not compact and not (query or "").strip():
        return None

    if exchange_hint and _is_compact_symbol(compact):
        cached = _RESOLVE_CACHE.get(f"{compact}|{exchange_hint}")
        if cached:
            return cached
        known = get_symbol_info(compact)
        name = known.get("name") or compact
        if name == compact:
            named = _RESOLVE_CACHE.get(f"{compact}|{exchange_hint}")
            if named and named.get("name"):
                name = named["name"]
        return remember_listing(_listing(
            compact,
            name,
            exchange_hint,
            sector=known.get("sector") or "Indian Equities",
            series=known.get("series") or "EQ",
        ))

    if compact in SYMBOL_MAP and not exchange_hint:
        return remember_listing(_from_local(SYMBOL_MAP[compact]))

    local_name_hits = _search_local(query, limit=8) if not _is_compact_symbol(compact) else []
    chosen = _unique_name_match(query, local_name_hits)
    if chosen:
        return remember_listing(chosen)

    if _is_compact_symbol(compact) and not exchange_hint:
        cached = _RESOLVE_CACHE.get(f"{compact}|")
        if cached:
            return cached

    name_key = "NAME|" + " ".join(_tokens(query))
    if name_key != "NAME|" and name_key in _RESOLVE_CACHE and not exchange_hint:
        cached_name = _RESOLVE_CACHE[name_key]
        if _name_score(query, cached_name.get("name", "")) >= 0.92:
            return cached_name

    if not remote:
        if _is_compact_symbol(compact):
            known = get_symbol_info(compact)
            return _listing(
                compact,
                known.get("name") or compact,
                "NSE",
                sector=known.get("sector") or "Indian Equities",
            )
        return None

    remote_hits = search_yahoo_equities(query, limit=8)
    if _is_compact_symbol(compact):
        exact = [row for row in remote_hits if row["symbol"] == compact]
        if exact:
            exact.sort(key=lambda row: 0 if row["exchange"] == "NSE" else 1)
            return remember_listing(exact[0])
        known = get_symbol_info(compact)
        return _listing(
            compact,
            known.get("name") or compact,
            "NSE",
            sector=known.get("sector") or "Indian Equities",
        )

    chosen = _unique_name_match(query, local_name_hits + remote_hits)
    if chosen:
        return remember_listing(chosen)
    return None
