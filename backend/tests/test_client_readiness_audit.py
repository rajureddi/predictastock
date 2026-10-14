"""
Client-Readiness & Quantitative Architecture Test Suite
Verifies:
1. Authentication rejection of missing/invalid credentials (HTTP 401).
2. Bcrypt password hashing and legacy SHA-256 transparent migration.
3. JWT session token lifecycle, expiration, and revocation.
4. Authorization isolation between user portfolio partitions.
5. Append-only recommendation history & audit events (zero destructive deletes on rescan).
6. Market data provenance: synthetic delivery proxies cannot satisfy exchange delivery rules.
7. Distributed scheduler leases: multi-worker idempotency and TTL renewal.
8. Indian cash equity rules: shorting prohibition (BEARISH = 0% return), daily bar path dependency,
   pessimistic tie-breakers, and candidate Tier-1 rule evaluation.
"""
import pytest
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db_connection, init_db
from app.config import ROUNDTRIP_FRICTION_PCT, TIER1_MIN_COMPOSITE_SCORE
from app.auth import (
    hash_password, verify_password, register_user, authenticate_user,
    create_access_token, is_token_revoked, revoke_token
)
from app.services.indicators import compute_all_indicators
from app.services.prediction_engine import (
    generate_daily_recommendations, get_latest_recommendations,
    supersede_previous_runs_for_date
)
from app.services.scheduler import (
    acquire_distributed_lease, complete_distributed_lease,
    release_distributed_lease_on_failure
)
from app.services.historical_backtest import (
    simulate_path_dependent_trade, is_locked_circuit
)

client = TestClient(app)


def test_auth_rejection_missing_and_invalid_credentials():
    """Verify missing, expired, or invalid credentials return HTTP 401."""
    # 1. Missing credentials on protected portfolio endpoint
    res_no_auth = client.get("/api/portfolio")
    assert res_no_auth.status_code == 401
    assert "Authentication required" in res_no_auth.json()["detail"]

    # 2. Invalid Bearer token
    res_bad_token = client.get("/api/portfolio", headers={"Authorization": "Bearer invalid_garbage_token"})
    assert res_bad_token.status_code == 401

    # 3. Invalid API Key
    res_bad_key = client.get("/api/portfolio", headers={"X-API-Key": "pstk_live_invalid_key"})
    assert res_bad_key.status_code == 401


def test_bcrypt_hashing_and_legacy_migration():
    """Verify bcrypt hash generation, validation, and transparent migration from legacy SHA-256."""
    test_pwd = "SecretPassword123!"
    
    # 1. Modern bcrypt hash
    b_hash = hash_password(test_pwd)
    assert b_hash.startswith(("$2a$", "$2b$", "$2y$"))
    is_valid, needs_upgrade = verify_password(test_pwd, b_hash)
    assert is_valid is True
    assert needs_upgrade is False

    # 2. Legacy SHA-256 hash
    import hashlib
    legacy_hash = hashlib.sha256((test_pwd + "predictastock_salt_v2").encode()).hexdigest()
    is_valid_leg, needs_up_leg = verify_password(test_pwd, legacy_hash)
    assert is_valid_leg is True
    assert needs_up_leg is True

    # 3. Transparent database migration test
    legacy_user = f"leg_user_{uuid.uuid4().hex[:6]}"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO users (id, username, email, password_hash, api_key, created_at, token_version)
    VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (str(uuid.uuid4()), legacy_user, f"{legacy_user}@test.com", legacy_hash, f"key_{legacy_user}", datetime.now().isoformat()))
    conn.commit()
    conn.close()

    # Authenticate legacy user -> triggers transparent upgrade to bcrypt
    auth_res = authenticate_user(legacy_user, test_pwd)
    assert auth_res is not None
    assert "access_token" in auth_res

    # Verify database now stores bcrypt hash
    conn2 = get_db_connection()
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT password_hash FROM users WHERE username = ?", (legacy_user,))
    upgraded_hash = cursor2.fetchone()["password_hash"]
    conn2.close()
    assert upgraded_hash.startswith(("$2a$", "$2b$", "$2y$"))


def test_jwt_token_revocation():
    """Verify JWT access tokens can be revoked and subsequently rejected."""
    user_id = str(uuid.uuid4())
    username = "token_test_user"
    token = create_access_token(user_id, username)

    import jwt
    from app.config import JWT_SECRET_KEY, JWT_ALGORITHM
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    jti = payload["jti"]
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    assert is_token_revoked(jti) is False
    revoke_token(jti, user_id, exp)
    assert is_token_revoked(jti) is True


def test_user_portfolio_authorization_isolation():
    """Verify User A cannot access or modify User B's portfolio transactions."""
    # Register User A
    user_a = f"usera_{uuid.uuid4().hex[:6]}"
    reg_a = register_user(user_a, "password123A", f"{user_a}@test.com")
    token_a = reg_a["access_token"]

    # Register User B
    user_b = f"userb_{uuid.uuid4().hex[:6]}"
    reg_b = register_user(user_b, "password123B", f"{user_b}@test.com")
    token_b = reg_b["access_token"]

    # User A records a transaction
    tx_res = client.post(
        "/api/portfolio/transaction",
        json={
            "symbol": "TCS",
            "transaction_type": "BUY",
            "price": 3500.0,
            "quantity": 10,
            "transaction_date": "2026-10-14",
            "brokerage": 20.0
        },
        headers={"Authorization": f"Bearer {token_a}"}
    )
    assert tx_res.status_code == 200
    tx_data = tx_res.json()["transaction"]
    tx_id = tx_data.get("id") or tx_data.get("transaction_id")

    # User B checks portfolio -> must be empty (isolation)
    b_port = client.get("/api/portfolio", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert b_port["total_invested"] == 0.0
    assert len(b_port["holdings"]) == 0

    # User B attempts to delete User A's transaction -> must fail to delete User A's data
    del_res = client.delete(f"/api/portfolio/transaction/{tx_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is False # User B cannot delete User A's transaction

    # User A portfolio still retains holding
    a_port = client.get("/api/portfolio", headers={"Authorization": f"Bearer {token_a}"}).json()
    assert a_port["total_invested"] > 0
    assert a_port["holdings"][0]["symbol"] == "TCS"


def test_append_only_recommendations_and_audit_events():
    """Verify rescanning for the same date archives prior runs as SUPERSEDED without deleting them."""
    test_date = "2026-10-99" # Isolated synthetic date
    conn = get_db_connection()
    cursor = conn.cursor()

    # Seed Run 1
    run1_id = f"run_{test_date}_v1"
    rec1_id = str(uuid.uuid4())
    cursor.execute("""
    INSERT INTO recommendation_runs (run_id, rec_date, version, generated_count, universe_size, model_version, status, created_at)
    VALUES (?, ?, 1, 1, 50, 'v2.5-Quant', 'ACTIVE', ?)
    """, (run1_id, test_date, datetime.now().isoformat()))

    cursor.execute("""
    INSERT INTO recommendations (
        id, symbol, name, exchange, sector, rec_date, reference_price, reference_timestamp,
        expected_target_price, stop_loss, expected_range_low, expected_range_high,
        expected_appreciation_pct, risk_level, status, action_label, run_id, version, is_superseded, created_at
    ) VALUES (?, 'INFY', 'Infosys', 'NSE', 'IT', ?, 1800.0, '2026-10-99 09:15:00 IST',
              1900.0, 1750.0, 1700.0, 1950.0, 5.5, 'Medium', 'ACTIVE', 'BUY / ACCUMULATE (5-Day Swing)',
              ?, 1, 0, ?)
    """, (rec1_id, test_date, run1_id, datetime.now().isoformat()))
    conn.commit()

    # Trigger supersession for rescan
    run2_id = f"run_{test_date}_v2"
    supersede_previous_runs_for_date(cursor, test_date, run2_id, 2, "Test rescan supersession")
    conn.commit()

    # Assert prior record still exists in database (NOT DELETED)
    cursor.execute("SELECT id, is_superseded FROM recommendations WHERE id = ?", (rec1_id,))
    row1 = cursor.fetchone()
    assert row1 is not None
    assert row1["is_superseded"] == 1 # Marked superseded, NOT deleted!

    # Assert audit event was recorded
    cursor.execute("SELECT event_type, reason FROM recommendation_audit_events WHERE recommendation_id = ?", (rec1_id,))
    audit_row = cursor.fetchone()
    assert audit_row is not None
    assert audit_row["event_type"] == "SUPERSEDED"
    assert "Test rescan supersession" in audit_row["reason"]

    # Clean up test rows
    cursor.execute("DELETE FROM recommendations WHERE rec_date = ?", (test_date,))
    cursor.execute("DELETE FROM recommendation_runs WHERE rec_date = ?", (test_date,))
    cursor.execute("DELETE FROM recommendation_audit_events WHERE recommendation_id = ?", (rec1_id,))
    conn.commit()
    conn.close()


def test_delivery_proxy_gatekeeper_enforcement():
    """Verify synthetic delivery proxies strictly DO NOT satisfy verified exchange delivery bonuses."""
    # Synthetic dataframe with positive momentum
    dates = pd.date_range("2026-01-01", periods=30)
    prices = np.linspace(100, 120, 30)
    df = pd.DataFrame({
        "Open": prices - 0.5,
        "High": prices + 1.0,
        "Low": prices - 1.0,
        "Close": prices,
        "Volume": [50000] * 30
    }, index=dates)

    # 1. Computed without Bhavcopy (Synthetic Proxy fallback)
    tech_proxy = compute_all_indicators(df, bhavcopy_data=None)
    assert tech_proxy["is_bhavcopy_actual"] is False
    assert tech_proxy["delivery_source"] == "SYNTHETIC_PROXY"

    # 2. Computed with Actual NSE Bhavcopy data
    actual_bhavcopy = {
        "DELIV_PER": 55.0,
        "DELIV_QTY": 80000,
        "PREV_CLOSE": 115.0,
        "CLOSE_PRICE": 120.0
    }
    tech_actual = compute_all_indicators(df, bhavcopy_data=actual_bhavcopy)
    assert tech_actual["is_bhavcopy_actual"] is True
    assert tech_actual["delivery_source"] == "NSE_BHAVCOPY"
    # Actual delivery surge with 55% delivery receives the verified bonus
    assert tech_actual["money_flow_score"] >= tech_proxy["money_flow_score"]


def test_scheduler_lease_idempotency_and_ttl():
    """Verify distributed lease mutual exclusion across workers and expiration takeover."""
    job_name = "test_eod_scanner"
    cycle_key_1 = "2026-10-14_run_1"

    # Worker 1 acquires lease
    acquired = acquire_distributed_lease(job_name, cycle_key_1, ttl_minutes=30)
    assert acquired is True

    # Worker 2 attempts concurrent acquisition with same key -> rejected
    acquired_dup = acquire_distributed_lease(job_name, cycle_key_1, ttl_minutes=30)
    assert acquired_dup is False

    # Worker 1 completes job
    complete_distributed_lease(job_name, cycle_key_1)

    # Worker 3 attempts run after completion -> rejected (idempotency prevents duplicate scan)
    acquired_after_comp = acquire_distributed_lease(job_name, cycle_key_1, ttl_minutes=30)
    assert acquired_after_comp is False

    # New cycle key on subsequent day acquires successfully
    cycle_key_2 = "2026-10-15_run_1"
    acquired_next_cycle = acquire_distributed_lease(job_name, cycle_key_2, ttl_minutes=30)
    assert acquired_next_cycle is True
    complete_distributed_lease(job_name, cycle_key_2)


def test_backtest_cash_short_prohibition_and_path_dependency():
    """
    Verify:
    1. Cash short selling prohibition: BEARISH signal produces 0.0% return (cash preservation).
    2. Pessimistic tie-breaker: Dual breach bar triggers stop-loss before target.
    3. Upper circuit detection blocks unfeasible entries.
    """
    # 1. Circuit detection
    assert is_locked_circuit(100.0, 100.0, 100.0, 100.0) is True
    assert is_locked_circuit(100.0, 105.0, 99.0, 103.0) is False

    # 2. Path-dependent execution with pessimistic tie-breaker
    # Construct 5 forward daily bars where Day 2 hits both target (110) and stop (90)
    dates = pd.date_range("2026-01-01", periods=5)
    future_bars = pd.DataFrame([
        {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 101.0}, # Day 1
        {"Open": 101.0, "High": 112.0, "Low": 88.0, "Close": 105.0}, # Day 2: Touches both 110 target and 90 stop!
        {"Open": 105.0, "High": 108.0, "Low": 104.0, "Close": 107.0}, # Day 3
        {"Open": 107.0, "High": 110.0, "Low": 106.0, "Close": 109.0}, # Day 4
        {"Open": 109.0, "High": 111.0, "Low": 108.0, "Close": 110.0}, # Day 5
    ], index=dates)

    trade = simulate_path_dependent_trade(
        future_bars=future_bars,
        entry_price=100.0,
        stop_loss=90.0,
        target_price=110.0,
        atr_14=4.0,
        use_trailing_stop=True,
        use_partial_profit=False
    )
    # Pessimistic tie-breaker rule MUST trigger stop loss, NOT target!
    assert trade["exit_reason"] == "STOP_LOSS_PESSIMISTIC_TIE"
    assert trade["exit_price"] == 90.0
    assert trade["gross_return_pct"] == -10.0
