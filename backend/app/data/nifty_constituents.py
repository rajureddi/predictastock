"""
Nifty 50 and Nifty 100 Constituents Data
Maps symbols, company names, sectors, and exchange identifiers.
"""
from typing import Dict, List, Any

# Primary Nifty 50 and representative Nifty 100 universe
NIFTY_UNIVERSE: List[Dict[str, Any]] = [
    # Top Heavyweights & Liquid Leaders across Sectors
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "sector": "Oil Gas & Consumable Fuels", "is_nifty50": True},
    {"symbol": "TCS", "name": "Tata Consultancy Services Ltd", "sector": "Information Technology", "is_nifty50": True},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "sector": "Telecommunication", "is_nifty50": True},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "INFY", "name": "Infosys Ltd", "sector": "Information Technology", "is_nifty50": True},
    {"symbol": "SBIN", "name": "State Bank of India", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "LICI", "name": "Life Insurance Corporation of India", "sector": "Financial Services", "is_nifty50": False},
    {"symbol": "ITC", "name": "ITC Ltd", "sector": "Fast Moving Consumer Goods", "is_nifty50": True},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd", "sector": "Fast Moving Consumer Goods", "is_nifty50": True},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "sector": "Construction", "is_nifty50": True},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd", "sector": "Information Technology", "is_nifty50": True},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "sector": "Automobile & Auto Components", "is_nifty50": True},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd", "sector": "Healthcare", "is_nifty50": True},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "sector": "Automobile & Auto Components", "is_nifty50": True},
    {"symbol": "ONGC", "name": "Oil & Natural Gas Corporation Ltd", "sector": "Oil Gas & Consumable Fuels", "is_nifty50": True},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "NTPC", "name": "NTPC Ltd", "sector": "Power", "is_nifty50": True},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "TITAN", "name": "Titan Company Ltd", "sector": "Consumer Durables", "is_nifty50": True},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "sector": "Metals & Mining", "is_nifty50": True},
    {"symbol": "ADANIPORTS", "name": "Adani Ports and SEZ Ltd", "sector": "Services", "is_nifty50": True},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Ltd", "sector": "Construction Materials", "is_nifty50": True},
    {"symbol": "COALINDIA", "name": "Coal India Ltd", "sector": "Oil Gas & Consumable Fuels", "is_nifty50": True},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India Ltd", "sector": "Power", "is_nifty50": True},
    {"symbol": "TATASTEEL", "name": "Tata Steel Ltd", "sector": "Metals & Mining", "is_nifty50": True},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Ltd", "sector": "Automobile & Auto Components", "is_nifty50": True},
    {"symbol": "NESTLEIND", "name": "Nestle India Ltd", "sector": "Fast Moving Consumer Goods", "is_nifty50": True},
    {"symbol": "WIPRO", "name": "Wipro Ltd", "sector": "Information Technology", "is_nifty50": True},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Ltd", "sector": "Metals & Mining", "is_nifty50": True},
    {"symbol": "GRASIM", "name": "Grasim Industries Ltd", "sector": "Construction Materials", "is_nifty50": True},
    {"symbol": "HINDALCO", "name": "Hindalco Industries Ltd", "sector": "Metals & Mining", "is_nifty50": True},
    {"symbol": "TECHM", "name": "Tech Mahindra Ltd", "sector": "Information Technology", "is_nifty50": True},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "CIPLA", "name": "Cipla Ltd", "sector": "Healthcare", "is_nifty50": True},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Ltd", "sector": "Healthcare", "is_nifty50": True},
    {"symbol": "EICHERMOT", "name": "Eicher Motors Ltd", "sector": "Automobile & Auto Components", "is_nifty50": True},
    {"symbol": "DIVISLAB", "name": "Divi's Laboratories Ltd", "sector": "Healthcare", "is_nifty50": True},
    {"symbol": "BPCL", "name": "Bharat Petroleum Corporation Ltd", "sector": "Oil Gas & Consumable Fuels", "is_nifty50": True},
    {"symbol": "BRITANNIA", "name": "Britannia Industries Ltd", "sector": "Fast Moving Consumer Goods", "is_nifty50": True},
    {"symbol": "APOLLOHOSP", "name": "Apollo Hospitals Enterprise Ltd", "sector": "Healthcare", "is_nifty50": True},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp Ltd", "sector": "Automobile & Auto Components", "is_nifty50": True},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Ltd", "sector": "Consumer Durables", "is_nifty50": True},
    {"symbol": "BAJAJ-AUTO", "name": "Bajaj Auto Ltd", "sector": "Automobile & Auto Components", "is_nifty50": True},
    {"symbol": "SHRIRAMFIN", "name": "Shriram Finance Ltd", "sector": "Financial Services", "is_nifty50": True},
    {"symbol": "TRENT", "name": "Trent Ltd", "sector": "Consumer Services", "is_nifty50": True},
    {"symbol": "BEL", "name": "Bharat Electronics Ltd", "sector": "Capital Goods", "is_nifty50": True},
    {"symbol": "HAL", "name": "Hindustan Aeronautics Ltd", "sector": "Capital Goods", "is_nifty50": False},
    {"symbol": "VEDL", "name": "Vedanta Ltd", "sector": "Metals & Mining", "is_nifty50": False},
    {"symbol": "ZOMATO", "name": "Zomato Ltd", "sector": "Consumer Services", "is_nifty50": False},
    {"symbol": "JIOFIN", "name": "Jio Financial Services Ltd", "sector": "Financial Services", "is_nifty50": False},
    {"symbol": "DLF", "name": "DLF Ltd", "sector": "Realty", "is_nifty50": False},
    {"symbol": "VBL", "name": "Varun Beverages Ltd", "sector": "Fast Moving Consumer Goods", "is_nifty50": False},
    {"symbol": "SIEMENS", "name": "Siemens Ltd", "sector": "Capital Goods", "is_nifty50": False},
    {"symbol": "PFC", "name": "Power Finance Corporation Ltd", "sector": "Financial Services", "is_nifty50": False},
    {"symbol": "RECLTD", "name": "REC Ltd", "sector": "Financial Services", "is_nifty50": False},
]

import json
from pathlib import Path

# Load complete National Stock Exchange (NSE) equity master list (~2,620 active listed equities)
_NSE_JSON_PATH = Path(__file__).parent / "nse_equities.json"
FULL_NSE_UNIVERSE: List[Dict[str, Any]] = []

def _infer_sector(name: str, symbol: str) -> str:
    known = {item["symbol"]: item["sector"] for item in NIFTY_UNIVERSE}
    if symbol in known:
        return known[symbol]
    name_u = name.upper()
    if "BANK" in name_u or "FINANC" in name_u or "CAPITAL" in name_u or "INVEST" in name_u:
        return "Financial Services"
    if "PHARMA" in name_u or "HEALTH" in name_u or "LAB" in name_u or "BIO" in name_u or "DRUG" in name_u:
        return "Healthcare & Pharma"
    if "TECH" in name_u or "INFO" in name_u or "SOFTWARE" in name_u or "DIGITAL" in name_u:
        return "Information Technology"
    if "MOTOR" in name_u or "AUTO" in name_u:
        return "Automobiles & Auto Components"
    if "POWER" in name_u or "ENERGY" in name_u or "SOLAR" in name_u or "ELECTRIC" in name_u:
        return "Power & Energy"
    if "STEEL" in name_u or "METAL" in name_u or "MINING" in name_u or "MINERAL" in name_u:
        return "Metals & Mining"
    if "CHEM" in name_u or "FERTIL" in name_u:
        return "Chemicals & Petrochemicals"
    if "INFRA" in name_u or "CONSTRUCT" in name_u or "ENGINEER" in name_u or "BUILD" in name_u:
        return "Capital Goods & Construction"
    if "REALTY" in name_u or "ESTATE" in name_u or "PROP" in name_u:
        return "Realty & Real Estate"
    if "OIL" in name_u or "GAS" in name_u or "PETRO" in name_u:
        return "Oil, Gas & Fuels"
    if "FOOD" in name_u or "BEVERAG" in name_u or "FMCG" in name_u or "AGRO" in name_u:
        return "Consumer Staples & FMCG"
    return "Diversified Industries"

def _load_all_equities():
    global FULL_NSE_UNIVERSE
    seen = set()
    # 1. Curated benchmark leaders first
    for item in NIFTY_UNIVERSE:
        FULL_NSE_UNIVERSE.append(item)
        seen.add(item["symbol"])

    # 2. Complete official NSE listed database
    if _NSE_JSON_PATH.exists():
        try:
            with open(_NSE_JSON_PATH, "r", encoding="utf-8") as f:
                raw_stocks = json.load(f)
            for s in raw_stocks:
                sym = s.get("symbol", "").strip().upper()
                if sym and sym not in seen:
                    FULL_NSE_UNIVERSE.append({
                        "symbol": sym,
                        "name": s.get("name", sym).strip(),
                        "sector": _infer_sector(s.get("name", sym), sym),
                        "series": s.get("series", "EQ"),
                        "isin": s.get("isin", ""),
                        "is_nifty50": False
                    })
                    seen.add(sym)
        except Exception:
            pass

_load_all_equities()

# Master lookup table across all 2,620+ Indian stocks
SYMBOL_MAP: Dict[str, Dict[str, Any]] = {item["symbol"]: item for item in FULL_NSE_UNIVERSE}


def get_all_symbols(only_nifty50: bool = False, full_market: bool = False) -> List[str]:
    """Retrieve symbols in the universe."""
    if only_nifty50:
        return [item["symbol"] for item in NIFTY_UNIVERSE if item.get("is_nifty50")]
    if full_market:
        return [item["symbol"] for item in FULL_NSE_UNIVERSE]
    return [item["symbol"] for item in NIFTY_UNIVERSE]


def get_symbol_info(symbol: str) -> Dict[str, Any]:
    """Lookup metadata for any Indian stock symbol across the complete NSE market."""
    clean = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    return SYMBOL_MAP.get(clean, {
        "symbol": clean,
        "name": clean,
        "sector": "Indian Equities",
        "is_nifty50": False
    })


def get_dynamic_bhavcopy_universe(
    min_turnover_cr: float = 10.0,
    min_price: float = 50.0,
    target_count: int = 250,
    sleeve1_count: int = 200,
    sleeve2_max: int = 50
) -> List[Dict[str, Any]]:
    """
    Dynamically select active scanning universe from official cached NSE EOD Bhavcopy
    using an Institutional Dual-Sleeve pre-screening architecture:
    
    1. Sleeve 1: Established Liquid Leaders (~200 stocks)
       - SERIES == 'EQ'
       - Daily Turnover >= ₹10 Crore (TURNOVER_LACS >= 1000)
       - Close Price >= ₹50
       - Ranked descending by turnover
       
    2. Sleeve 2: Sudden Momentum & Institutional Delivery Outliers (~30-50 stocks)
       - Catches miscellaneous mid/small-caps with explosive daily moves
       - Daily Gain >= +4.5% (and < 20% to avoid illiquid locked circuits)
       - Daily Turnover >= ₹5 Crore (TURNOVER_LACS >= 500)
       - Real Demat Delivery >= 40% (confirms institutional buying vs day-trader churn)
       - Close Price >= ₹30 (no micro/penny stocks)
       - Ranked descending by daily gain %
       
    3. Merged Universe: Combines Sleeve 1 + Sleeve 2 without duplicates (up to target_count).
    4. Fallback: Cleanly defaults to NIFTY_UNIVERSE if Bhavcopy is unavailable.
    """
    try:
        from app.services.market_data import load_nse_bhavcopy
        bhav_map = load_nse_bhavcopy()
        if not bhav_map:
            return list(NIFTY_UNIVERSE)

        # Filter only base symbols (avoid duplicates with .NS)
        base_stocks = [v for k, v in bhav_map.items() if not k.endswith('.NS')]
        min_turnover_lacs = min_turnover_cr * 100.0  # ₹10 Cr = 1000 Lakhs

        # -------------------------------------------------------------
        # SLEEVE 1: Top Liquid Market Leaders
        # -------------------------------------------------------------
        sleeve_1_candidates = []
        for s in base_stocks:
            turnover = s.get('turnover_lacs', 0.0)
            price = s.get('close_price', 0.0)
            if turnover >= min_turnover_lacs and price >= min_price:
                sym = s['symbol']
                info = get_symbol_info(sym)
                sleeve_1_candidates.append({
                    "symbol": sym,
                    "name": info.get("name", sym),
                    "sector": info.get("sector", "Indian Equities"),
                    "is_nifty50": info.get("is_nifty50", False),
                    "turnover_lacs": turnover,
                    "close_price": price,
                    "sleeve": "LIQUID_LEADER"
                })

        sleeve_1_candidates.sort(key=lambda x: x["turnover_lacs"], reverse=True)
        selected_sleeve_1 = sleeve_1_candidates[:sleeve1_count]
        seen_symbols = {s["symbol"] for s in selected_sleeve_1}

        # -------------------------------------------------------------
        # SLEEVE 2: Sudden Momentum & Delivery Breakout Radar
        # -------------------------------------------------------------
        sleeve_2_candidates = []
        for s in base_stocks:
            sym = s['symbol']
            if sym in seen_symbols:
                continue

            price = s.get('close_price', 0.0)
            prev_price = s.get('prev_close', 0.0)
            turnover = s.get('turnover_lacs', 0.0)
            deliv_p = s.get('deliv_per', 0.0)

            if prev_price > 0:
                gain_pct = ((price - prev_price) / prev_price) * 100.0
                # Filter: gain >= +4.5%, turnover >= ₹5 Cr, deliv >= 40%, price >= 30, not 20% upper-circuit locked
                if (gain_pct >= 4.5 and turnover >= 500.0 and deliv_p >= 40.0 and price >= 30.0 and gain_pct < 20.0):
                    info = get_symbol_info(sym)
                    sleeve_2_candidates.append({
                        "symbol": sym,
                        "name": info.get("name", sym),
                        "sector": info.get("sector", "Indian Equities"),
                        "is_nifty50": info.get("is_nifty50", False),
                        "turnover_lacs": turnover,
                        "close_price": price,
                        "daily_gain_pct": round(gain_pct, 2),
                        "deliv_per": deliv_p,
                        "sleeve": "OUTLIER_SURGE"
                    })

        sleeve_2_candidates.sort(key=lambda x: x.get("daily_gain_pct", 0.0), reverse=True)
        selected_sleeve_2 = sleeve_2_candidates[:sleeve2_max]

        # Merge Sleeves
        combined_universe = selected_sleeve_1 + selected_sleeve_2
        if not combined_universe:
            return list(NIFTY_UNIVERSE)

        import logging
        logging.getLogger(__name__).info(
            f"Dual-Sleeve Pre-Screener indexed {len(combined_universe)} stocks "
            f"({len(selected_sleeve_1)} Liquid Leaders + {len(selected_sleeve_2)} Outlier Breakouts)."
        )
        return combined_universe[:target_count]
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Error loading dual-sleeve Bhavcopy universe: {e}. Falling back to NIFTY_UNIVERSE.")
        return list(NIFTY_UNIVERSE)


