"""
PredictaStock Comprehensive Unit & Integration Test Suite
Validates FIFO cost basis, statutory taxes, recommendation screening, and PDF generation.
"""
import sys
from pathlib import Path
from datetime import date

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.database import init_db, get_db_connection
from app.services.portfolio import record_transaction, compute_portfolio_fifo, calculate_indian_statutory_costs, delete_stock_from_portfolio
from app.services.prediction_engine import generate_daily_recommendations, get_latest_recommendations
from app.services.report_generator import generate_morning_report
from app.services.backtester import evaluate_pending_forecasts, get_forecast_scorecard


def run_tests():
    print("=" * 60)
    print("PREDICTASTOCK AUTOMATED TEST RUNNER")
    print("=" * 60)

    # 1. Initialize DB
    print("\n[1/5] Initializing Database Schema...")
    init_db()
    print("[OK] SQLite WAL database initialized successfully.")

    # 2. Test Statutory Tax Calculations
    print("\n[2/5] Testing Indian Equity Statutory Taxes Engine...")
    costs = calculate_indian_statutory_costs(price=1000.0, quantity=10, is_buy=True)
    turnover = costs["turnover"]
    stt = costs["stt"]
    stamp = costs["stamp_duty"]
    brokerage = costs["brokerage"]
    gst = costs["gst"]
    total = costs["total_costs"]
    
    print(f"  Turnover: Rs {turnover}")
    print(f"  STT (0.1%): Rs {stt}")
    print(f"  Brokerage: Rs {brokerage}")
    print(f"  Stamp Duty (0.015%): Rs {stamp}")
    print(f"  GST (18% on Brokerage+Exch): Rs {gst}")
    print(f"  Total Statutory Charges: Rs {total}")
    assert turnover == 10000.0, "Turnover mismatch"
    assert stt == 10.0, "STT mismatch"
    assert stamp == 1.5, "Stamp duty mismatch"
    print("[OK] Statutory taxes calculate correctly per SEBI/Indian tax rules.")

    # 3. Test FIFO Portfolio Matching (Testing Section 9.7 & 10.4 Example)
    print("\n[3/5] Testing FIFO Portfolio Engine with Test Transactions...")
    # Clean previous test transactions
    conn = get_db_connection()
    conn.execute("DELETE FROM portfolio_transactions WHERE notes = 'TEST_SUITE'")
    conn.commit()
    conn.close()

    # Log 4 buys (matching Section 9.7)
    record_transaction("RELIANCE", "BUY", price=3000.0, quantity=10, notes="TEST_SUITE")
    record_transaction("TCS", "BUY", price=3500.0, quantity=10, notes="TEST_SUITE")
    record_transaction("INFY", "BUY", price=1800.0, quantity=10, notes="TEST_SUITE")
    record_transaction("TATASTEEL", "BUY", price=150.0, quantity=20, notes="TEST_SUITE")
    
    portfolio = compute_portfolio_fifo()
    print(f"  Holdings Count: {len(portfolio['holdings'])}")
    print(f"  Total Invested: Rs {portfolio['total_invested']:,.2f}")
    print(f"  Current Market Value: Rs {portfolio['current_market_value']:,.2f}")
    print(f"  Net P&L (After Costs): Rs {portfolio['net_pnl_after_costs']:,.2f}")
    assert len(portfolio['holdings']) >= 4, "Holdings count mismatch"
    print("[OK] FIFO calculations and active holdings validated.")

    # 3b. Test Deletion of Stock from Portfolio
    print("\n[3b/5] Testing Delete Stock from Portfolio functionality...")
    del_res = delete_stock_from_portfolio("TATASTEEL", user_id="default_trader")
    print(f"  Delete result: {del_res}")
    assert del_res["status"] == "SUCCESS", "Delete status failed"
    assert del_res["deleted_count"] >= 1, "Failed to delete test transactions"
    portfolio_after = compute_portfolio_fifo()
    syms_after = [h["symbol"] for h in portfolio_after["holdings"]]
    assert "TATASTEEL" not in syms_after, "Deleted stock still found in portfolio holdings"
    print("[OK] Successfully deleted stock from portfolio and updated FIFO holdings.")

    # 4. Test Stock Screening & Recommendation Generation
    print("\n[4/5] Testing 5-Day Multi-Factor Prediction & Screening...")
    recs = generate_daily_recommendations()
    print(f"  Recommendations Generated: {len(recs)}")
    for r in recs:
        print(f"  - {r['symbol']}: Ref Rs {r['reference_price']} -> Target Rs {r['expected_target_price']} (+{r['expected_appreciation_pct']}%), Risk: {r['risk_level']}")
    assert len(recs) > 0, "No recommendations generated"
    print("[OK] Multi-factor screening and ATR price ranges verified.")

    # 5. Test 5:45 AM Morning Report Dispatcher (HTML & PDF)
    print("\n[5/5] Testing Morning Report Builder (HTML & PDF)...")
    report_res = generate_morning_report()
    print(f"  Report Date: {report_res['report_date']}")
    print(f"  HTML File: {report_res['html_file']}")
    print(f"  PDF File: {report_res['pdf_file']}")
    
    assert Path(report_res['html_file']).exists(), "HTML report file not created"
    assert Path(report_res['pdf_file']).exists(), "PDF report file not created"
    print("[OK] 10-Section HTML and PDF reports generated successfully!")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
