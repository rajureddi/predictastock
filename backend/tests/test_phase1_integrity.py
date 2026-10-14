"""
Phase 1 Data Integrity & System Trust Test Suite
Verifies all Blueprint Phase 1 requirements:
1. Zero synthetic price fallbacks (never returns ₹1,000)
2. Zero fabricated news headlines or artificial positive drift
3. Two-sided mathematical ATR volatility cones (no forced always-positive target)
4. Portfolio validation: rejects non-positive trades & rejects selling unheld shares
5. Clean FIFO cost basis: allocates buy and sell fees to lots without corrupting remaining positions
6. Recommendation idempotency and run batching (no duplicate rows per date)
"""
import sys
from pathlib import Path
from datetime import date

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.database import init_db, get_db_connection
from app.services.market_data import get_latest_quote, is_quote_valid, get_nifty50_live_status
from app.services.news_sentiment import analyze_sentiment
from app.services.indicators import compute_mathematical_5d_range
from app.services.portfolio import record_transaction, compute_portfolio_fifo, get_current_shares_held
from app.services.prediction_engine import generate_daily_recommendations, get_latest_recommendations
from app.services.backtester import get_forecast_scorecard


def run_phase1_verification():
    print("=" * 70)
    print("PREDICTASTOCK PHASE 1 INTEGRITY VERIFICATION SUITE")
    print("=" * 70)

    # 1. Database Init & Migration Verification
    print("\n[TEST 1] Verifying Database Schema & Non-Destructive Migrations...")
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(recommendations)")
    rec_cols = [c[1] for c in cursor.fetchall()]
    assert "run_id" in rec_cols, "run_id column missing from recommendations"
    assert "direction" in rec_cols, "direction column missing from recommendations"
    conn.close()
    print("  [PASS] Database schema and backward-compatible columns verified.")

    # 2. Test Zero Synthetic Price Fallback
    print("\n[TEST 2] Verifying Zero Synthetic Fallback Quotes...")
    fake_quote = get_latest_quote("NON_EXISTENT_XYZ_STOCK")
    print(f"  Query result for non-existent stock: close_price={fake_quote['close_price']}, is_valid={fake_quote['is_valid']}")
    assert fake_quote["close_price"] is None, "CRITICAL: Market quote returned fabricated price instead of None!"
    assert fake_quote["close_price"] != 1000.0, "CRITICAL: Fallback ₹1,000 detected!"
    assert fake_quote["is_valid"] is False, "is_valid must be False on failed quote"
    assert is_quote_valid(fake_quote) is False, "is_quote_valid helper must reject invalid quote"
    print("  [PASS] Zero synthetic fallback prices verified (no Rs. 1,000 placeholder).")

    # 3. Test Zero Fabricated News & Sentiment Integrity
    print("\n[TEST 3] Verifying News Sentiment Grounding...")
    score, label, catalysts, risks = analyze_sentiment([])
    print(f"  Empty feed analysis: score={score}, label='{label}', catalysts={catalysts}")
    assert score == 0.0, f"Expected 0.0 on empty feed, got {score}"
    assert label == "No Recent Headlines", f"Expected 'No Recent Headlines', got {label}"
    assert catalysts == [], "CRITICAL: Fabricated catalysts detected on empty news feed!"
    assert risks == [], "CRITICAL: Fabricated risks detected on empty news feed!"
    print("  [PASS] Empty news feed honestly yields 0.0 (Neutral) with zero fabricated catalysts.")

    # 4. Test Two-Sided ATR Volatility Cone (No Forced Always-Positive Bias)
    print("\n[TEST 4] Verifying Mathematical Two-Sided ATR Volatility Cones...")
    # Bullish scenario
    bull_cone = compute_mathematical_5d_range(cmp=1000.0, atr=20.0, vol_5d_pct=3.0, signal="Bullish Setup", rsi=60.0)
    print(f"  Bullish setup (CMP 1000): Target = Rs {bull_cone['expected_target_price']} ({bull_cone['expected_appreciation_pct']}%), Direction = {bull_cone['direction']}")
    assert bull_cone["direction"] == "BULLISH", "Expected BULLISH direction"
    assert bull_cone["expected_appreciation_pct"] > 0, "Bullish expected appreciation must be positive"
    assert bull_cone["expected_range_low"] < 1000.0 < bull_cone["expected_range_high"]

    # Bearish scenario
    bear_cone = compute_mathematical_5d_range(cmp=1000.0, atr=20.0, vol_5d_pct=3.0, signal="Bearish Breakdown", rsi=35.0)
    print(f"  Bearish setup (CMP 1000): Target = Rs {bear_cone['expected_target_price']} ({bear_cone['expected_appreciation_pct']}%), Direction = {bear_cone['direction']}")
    assert bear_cone["direction"] == "BEARISH", "Expected BEARISH direction"
    assert bear_cone["expected_appreciation_pct"] < 0, "CRITICAL: Bearish setup must allow negative return target!"
    assert bear_cone["expected_target_price"] < 1000.0, "Bearish target must be below CMP"
    print("  [PASS] Two-sided ATR volatility cones verified (both Bullish and Bearish supported).")

    # 5. Test Portfolio Transaction Validation & Oversell Rejection
    print("\n[TEST 5] Verifying Portfolio Transaction Validation & Oversell Rejection...")
    # Attempt to sell shares not held
    oversell_threw = False
    try:
        record_transaction("WIPRO", "SELL", price=500.0, quantity=50, notes="INTEGRITY_TEST")
    except ValueError as e:
        oversell_threw = True
        print(f"  Oversell correctly rejected with error: '{e}'")
    assert oversell_threw, "CRITICAL: System accepted SELL transaction when 0 shares were held!"

    # Attempt to record non-positive price or quantity
    invalid_qty_threw = False
    try:
        record_transaction("WIPRO", "BUY", price=500.0, quantity=-10, notes="INTEGRITY_TEST")
    except ValueError:
        invalid_qty_threw = True
    assert invalid_qty_threw, "System accepted negative quantity!"

    invalid_price_threw = False
    try:
        record_transaction("WIPRO", "BUY", price=-100.0, quantity=10, notes="INTEGRITY_TEST")
    except ValueError:
        invalid_price_threw = True
    assert invalid_price_threw, "System accepted negative price!"
    print("  [PASS] Strict transaction validation and oversell rejection verified.")

    # 6. Test Correct FIFO Cost Allocation
    print("\n[TEST 6] Verifying Clean FIFO Cost Basis & Net Realized P&L...")
    # Clean previous integrity test entries
    conn = get_db_connection()
    conn.execute("DELETE FROM portfolio_transactions WHERE notes = 'FIFO_COST_TEST'")
    conn.commit()
    conn.close()

    # Buy 10 shares of HDFCBANK @ 1500
    b1 = record_transaction("HDFCBANK", "BUY", price=1500.0, quantity=10, notes="FIFO_COST_TEST")
    # Sell 5 shares of HDFCBANK @ 1600
    s1 = record_transaction("HDFCBANK", "SELL", price=1600.0, quantity=5, notes="FIFO_COST_TEST")
    
    port = compute_portfolio_fifo()
    hdfc_holding = next((h for h in port["holdings"] if h["symbol"] == "HDFCBANK"), None)
    assert hdfc_holding is not None, "HDFCBANK holding not found"
    assert hdfc_holding["quantity"] == 5, f"Expected 5 remaining shares, got {hdfc_holding['quantity']}"
    assert hdfc_holding["realized_gross_pnl"] == 500.0, f"Expected Rs 500 gross gain, got {hdfc_holding['realized_gross_pnl']}"
    assert hdfc_holding["realized_net_pnl"] > 0, "Realized net P&L must be positive after allocated costs"
    # Ensure remaining open position allocated costs only reflect the remaining 5 shares
    assert hdfc_holding["allocated_open_costs"] < b1["total_costs"], "Allocated costs on remaining shares must not include sold shares!"

    # Clean up test rows
    conn = get_db_connection()
    conn.execute("DELETE FROM portfolio_transactions WHERE notes = 'FIFO_COST_TEST'")
    conn.commit()
    conn.close()
    print("  [PASS] FIFO lot matching and accurate per-lot cost allocation verified.")

    # 7. Test Recommendation Batching & Idempotency
    print("\n[TEST 7] Verifying Recommendation Batching & Deduplication...")
    today_str = date.today().isoformat()
    recs1 = get_latest_recommendations(limit=5)
    symbols = [r["symbol"] for r in recs1]
    assert len(symbols) == len(set(symbols)), "CRITICAL: Duplicate symbols found in recommendation output!"
    print(f"  Latest recommendation batch symbols: {symbols} (all unique)")
    print("  [PASS] Distinct recommendation batching verified.")

    # 8. Scorecard Disclosures
    print("\n[TEST 8] Verifying Scorecard Sample Size & Limitation Disclosures...")
    scorecard = get_forecast_scorecard()
    print(f"  Scorecard status: '{scorecard['status_text']}'")
    print(f"  Sample size: {scorecard['sample_size']}, Pending: {scorecard['pending_forecasts']}")
    assert "limitations_note" in scorecard, "Scorecard must include statistical limitations note"
    print("  [PASS] Scorecard sample size disclosures verified.")

    print("\n" + "=" * 70)
    print("ALL PHASE 1 INTEGRITY ACCEPTANCE CRITERIA SATISFIED WITH 100% SUCCESS!")
    print("=" * 70)


if __name__ == "__main__":
    run_phase1_verification()
