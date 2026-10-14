"""
PredictaStock Database Engine
Uses SQLite with Write-Ahead Logging (WAL) for high concurrency, durability, and immutable auditability.
Complies with Section 15.1 (Persistent Storage) and Section 15.2 (Daily Backups).
"""
import sqlite3
import shutil
from datetime import datetime, date
from pathlib import Path
from typing import Generator
from app.config import DB_PATH, DATA_DIR


def get_db_connection() -> sqlite3.Connection:
    """Create and return an optimized SQLite connection with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """Initialize all schema tables and indexes."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Recommendations Table (Immutable Original Records)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recommendations (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        name TEXT NOT NULL,
        exchange TEXT NOT NULL DEFAULT 'NSE',
        sector TEXT,
        rec_date TEXT NOT NULL,
        reference_price REAL NOT NULL,
        reference_timestamp TEXT NOT NULL,
        expected_target_price REAL NOT NULL,
        expected_range_low REAL NOT NULL,
        expected_range_high REAL NOT NULL,
        expected_appreciation_pct REAL NOT NULL,
        risk_level TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Positive — Outlook Maintained',
        supporting_reasons TEXT,
        downside_risks TEXT,
        technical_summary TEXT,
        fundamental_summary TEXT,
        news_summary TEXT,
        sentiment_score REAL DEFAULT 0.0,
        sentiment_label TEXT DEFAULT 'Neutral',
        atr_14 REAL DEFAULT 0.0,
        volatility_5d_pct REAL DEFAULT 0.0,
        support_level REAL,
        resistance_level REAL,
        confidence_text TEXT DEFAULT 'Not enough history yet to measure accuracy',
        model_version TEXT NOT NULL DEFAULT 'v2.0-QuantHybrid',
        created_at TEXT NOT NULL
    );
    """)

    # 2. Daily Recommendation Updates Table (Daily Tracking & Downgrade History)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recommendation_updates (
        id TEXT PRIMARY KEY,
        recommendation_id TEXT NOT NULL,
        update_date TEXT NOT NULL,
        current_price REAL NOT NULL,
        pct_change_since_rec REAL NOT NULL,
        pct_change_session REAL NOT NULL,
        status TEXT NOT NULL,
        reason_for_change TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
    );
    """)

    # 3. Portfolio Transactions Table (User Purchases & Sales Ledger)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_transactions (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        exchange TEXT NOT NULL DEFAULT 'NSE',
        transaction_type TEXT NOT NULL, -- 'BUY' or 'SELL'
        transaction_date TEXT NOT NULL,
        price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        amount REAL NOT NULL,
        brokerage REAL DEFAULT 0.0,
        stt REAL DEFAULT 0.0,
        exchange_charges REAL DEFAULT 0.0,
        stamp_duty REAL DEFAULT 0.0,
        gst REAL DEFAULT 0.0,
        total_costs REAL DEFAULT 0.0,
        recommendation_id TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
    );
    """)

    # 4. Forecast Evaluations Table (Strict 5-Trading-Day Evaluation vs Nifty 50)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS forecast_evaluations (
        id TEXT PRIMARY KEY,
        recommendation_id TEXT NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        original_reference_price REAL NOT NULL,
        predicted_target_price REAL NOT NULL,
        predicted_appreciation_pct REAL NOT NULL,
        actual_end_price REAL,
        actual_appreciation_pct REAL,
        forecast_error_pct REAL,
        direction_correct INTEGER, -- 1 for True, 0 for False, NULL if pending
        nifty50_start_price REAL,
        nifty50_end_price REAL,
        nifty50_return_pct REAL,
        alpha_vs_nifty_pct REAL,
        user_actual_buy_price REAL,
        user_actual_return_pct REAL,
        status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'COMPLETED', 'EXCEPTION'
        evaluated_at TEXT,
        FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
    );
    """)

    # 5. Daily Reports Audit Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_reports (
        id TEXT PRIMARY KEY,
        report_date TEXT NOT NULL UNIQUE,
        generated_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'GENERATED',
        html_file_path TEXT,
        pdf_file_path TEXT,
        summary_text TEXT,
        missing_components TEXT,
        email_sent INTEGER DEFAULT 0,
        email_sent_at TEXT
    );
    """)

    # 6. Corporate Actions Table (Splits, Bonus, Dividends)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS corporate_actions (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        action_type TEXT NOT NULL, -- 'SPLIT', 'BONUS', 'DIVIDEND'
        record_date TEXT NOT NULL,
        ex_date TEXT NOT NULL,
        ratio TEXT,
        adjustment_factor REAL NOT NULL DEFAULT 1.0,
        dividend_amount REAL DEFAULT 0.0,
        applied INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """)

    # 7. Sourced Company Fundamentals Table (Actual Financial Statements)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS company_fundamentals (
        symbol TEXT PRIMARY KEY,
        name TEXT,
        sector TEXT,
        pe_ratio REAL,
        pb_ratio REAL,
        roe REAL,
        roce REAL,
        debt_to_equity REAL,
        revenue_growth_yoy REAL,
        operating_margin REAL,
        market_cap_cr REAL,
        fundamental_score REAL,
        data_source TEXT NOT NULL,
        observation_date TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 8. Multi-Source Price Observations & Verification Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_observations (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        observation_date TEXT NOT NULL,
        primary_source TEXT NOT NULL,
        primary_price REAL,
        backup_source TEXT,
        backup_price REAL,
        discrepancy_pct REAL,
        validation_status TEXT NOT NULL, -- 'VERIFIED', 'UNCERTAIN', 'FAILED'
        observation_timestamp TEXT NOT NULL
    );
    """)

    # 9. Secure User Accounts Table (Portfolio Privacy)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        email TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        api_key TEXT UNIQUE,
        created_at TEXT NOT NULL
    );
    """)

    # 10. Official NSE Equities Master Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nse_equities (
        symbol TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        sector TEXT,
        series TEXT,
        isin TEXT,
        is_nifty50 INTEGER DEFAULT 0,
        updated_at TEXT NOT NULL
    );
    """)

    # Useful Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations(rec_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rec_symbol ON recommendations(symbol);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_symbol ON portfolio_transactions(symbol);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_eval_status ON forecast_evaluations(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_obs ON price_observations(symbol, observation_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_nse_name ON nse_equities(name);")

    # Seed NSE Equities if empty
    cursor.execute("SELECT COUNT(*) FROM nse_equities")
    if cursor.fetchone()[0] == 0:
        import json
        from pathlib import Path
        json_file = Path(__file__).parent / "data" / "nse_equities.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    equities = json.load(f)
                from app.data.nifty_constituents import _infer_sector, NIFTY_UNIVERSE
                nifty50_set = {s["symbol"] for s in NIFTY_UNIVERSE if s.get("is_nifty50")}
                now_ts = datetime.now().isoformat()
                cursor.executemany("""
                INSERT OR IGNORE INTO nse_equities (symbol, name, sector, series, isin, is_nifty50, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, [
                    (
                        eq["symbol"],
                        eq.get("name", eq["symbol"]),
                        _infer_sector(eq.get("name", eq["symbol"]), eq["symbol"]),
                        eq.get("series", "EQ"),
                        eq.get("isin", ""),
                        1 if eq["symbol"] in nifty50_set else 0,
                        now_ts
                    )
                    for eq in equities
                ])
            except Exception as e:
                logger.warning(f"Could not seed nse_equities: {e}")

    # Safe Backward-Compatible Migrations
    def safe_add_column(table: str, col_def: str):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def};")
        except sqlite3.OperationalError:
            pass # Column already exists

    safe_add_column("recommendations", "run_id TEXT")
    safe_add_column("recommendations", "direction TEXT DEFAULT 'BULLISH'")
    safe_add_column("recommendations", "composite_score REAL DEFAULT 65.0")
    safe_add_column("recommendations", "stop_loss REAL DEFAULT 0.0")
    safe_add_column("recommendations", "action_label TEXT DEFAULT 'BUY / ACCUMULATE (5-Day Swing)'")
    safe_add_column("recommendations", "cmf_20 REAL DEFAULT 0.0")
    safe_add_column("recommendations", "vol_surge REAL DEFAULT 1.0")
    safe_add_column("recommendations", "deliv_per REAL DEFAULT 45.0")
    safe_add_column("recommendations", "deliv_surge REAL DEFAULT 1.0")
    safe_add_column("recommendations", "rs_20d REAL DEFAULT 0.0")
    safe_add_column("recommendations", "ai_thesis TEXT")
    safe_add_column("recommendations", "delivery_source TEXT DEFAULT 'NSE_BHAVCOPY'")
    safe_add_column("forecast_evaluations", "predicted_direction TEXT DEFAULT 'BULLISH'")
    safe_add_column("forecast_evaluations", "exception_reason TEXT")
    safe_add_column("forecast_evaluations", "run_id TEXT")
    safe_add_column("portfolio_transactions", "user_id TEXT DEFAULT 'default_trader'")
    safe_add_column("daily_reports", "delivery_status TEXT DEFAULT 'PENDING'")
    safe_add_column("daily_reports", "recipient_email TEXT")

    # Seed default local user for seamless backward compatibility
    cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'default_trader'")
    if cursor.fetchone()[0] == 0:
        import hashlib
        default_pwd_hash = hashlib.sha256("trader123".encode()).hexdigest()
        cursor.execute("""
        INSERT INTO users (id, username, email, password_hash, api_key, created_at)
        VALUES ('usr_default_trader', 'default_trader', 'trader@predictastock.internal', ?, 'pstk_live_key_default', ?)
        """, (default_pwd_hash, datetime.now().isoformat()))

    conn.commit()
    conn.close()


def backup_database() -> Path:
    """Create an automated daily snapshot backup of the SQLite database."""
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    today_str = date.today().isoformat()
    backup_file = backup_dir / f"predictastock_backup_{today_str}.db"
    
    # Secure backup using SQLite VACUUM INTO or file copy
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"VACUUM INTO '{str(backup_file).replace('\\', '/')}';")
    conn.close()
    return backup_file
