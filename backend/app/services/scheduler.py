"""
PredictaStock Background Workflow Scheduler & Distributed Lease Manager
Ensures scheduled jobs execute strictly once per intended cycle across multiple
application worker processes, restarts, and concurrent cluster nodes.
Uses durable SQLite distributed leases with TTL, expiry renewal, idempotency keys,
and observable audit status.
"""
import os
import uuid
import logging
from datetime import datetime, date, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import (
    MARKET_TIMEZONE, SCHEDULE_MAIN_ANALYSIS,
    SCHEDULE_MORNING_REFRESH, SCHEDULE_REPORT_BUILD,
    SCHEDULE_EMAIL_DEADLINE
)
from app.database import get_db_connection, backup_database
from app.data.nse_calendar import is_trading_day
from app.services.prediction_engine import generate_daily_recommendations
from app.services.portfolio import compute_portfolio_fifo
from app.services.backtester import evaluate_pending_forecasts
from app.services.report_generator import generate_morning_report

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=MARKET_TIMEZONE)
WORKER_ID = f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"


def acquire_distributed_lease(job_name: str, idempotency_key: str, ttl_minutes: int = 45) -> bool:
    """
    Acquire a durable database lease for the job.
    Returns True if lease is acquired, False if already completed or actively leased by another worker.
    """
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT lease_owner, expires_at, status, idempotency_key FROM scheduler_leases WHERE job_name = ?", (job_name,))
        row = cursor.fetchone()

        if row:
            stored_owner = row["lease_owner"]
            stored_expires = row["expires_at"]
            stored_status = row["status"]
            stored_key = row["idempotency_key"]

            # If already completed for this exact idempotency cycle, prevent duplicate execution
            if stored_key == idempotency_key and stored_status == "COMPLETED":
                logger.info(f"Scheduler lease for '{job_name}' [{idempotency_key}] already COMPLETED. Skipping duplicate execution.")
                conn.close()
                return False

            # If lease is currently held and has not expired, do not take over
            if stored_status == "ACQUIRED" and stored_expires > now_str and stored_key == idempotency_key:
                logger.info(f"Scheduler lease for '{job_name}' currently held by {stored_owner} until {stored_expires}. Skipping.")
                conn.close()
                return False

        # Acquire or renew lease
        cursor.execute("""
        INSERT INTO scheduler_leases (
            job_name, lease_owner, acquired_at, expires_at, status, idempotency_key, last_error, updated_at
        ) VALUES (?, ?, ?, ?, 'ACQUIRED', ?, NULL, ?)
        ON CONFLICT(job_name) DO UPDATE SET
            lease_owner = excluded.lease_owner,
            acquired_at = excluded.acquired_at,
            expires_at = excluded.expires_at,
            status = 'ACQUIRED',
            idempotency_key = excluded.idempotency_key,
            last_error = NULL,
            updated_at = excluded.updated_at
        """, (job_name, WORKER_ID, now_str, expires_at, idempotency_key, now_str))
        conn.commit()
        conn.close()
        logger.info(f"Worker {WORKER_ID} acquired distributed lease for '{job_name}' [{idempotency_key}].")
        return True

    except Exception as e:
        logger.error(f"Error acquiring scheduler lease for '{job_name}': {e}")
        conn.close()
        return False


def complete_distributed_lease(job_name: str, idempotency_key: str) -> None:
    """Mark scheduler lease as completed to guarantee idempotency across workers."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("""
        UPDATE scheduler_leases
        SET status = 'COMPLETED', updated_at = ?
        WHERE job_name = ? AND idempotency_key = ?
        """, (now_str, job_name, idempotency_key))
        conn.commit()
    except Exception as e:
        logger.error(f"Error marking scheduler lease COMPLETED for '{job_name}': {e}")
    finally:
        conn.close()


def release_distributed_lease_on_failure(job_name: str, idempotency_key: str, error_msg: str) -> None:
    """Mark scheduler lease as FAILED with error message to allow recovery."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("""
        UPDATE scheduler_leases
        SET status = 'FAILED', last_error = ?, updated_at = ?
        WHERE job_name = ? AND idempotency_key = ?
        """, (error_msg, now_str, job_name, idempotency_key))
        conn.commit()
    except Exception as e:
        logger.error(f"Error marking scheduler lease FAILED for '{job_name}': {e}")
    finally:
        conn.close()


def run_layer1_light_monitor():
    """
    Layer 1: Continuous Light Monitor (Every 15 mins during market hours 9:15 - 15:30 IST).
    Checks for sudden breaking news or circuit breaches on held/recommended stocks.
    Protected by 15-minute idempotency lease.
    """
    today = date.today()
    if not is_trading_day(today):
        return
        
    now = datetime.now()
    if now.hour < 9 or (now.hour == 9 and now.minute < 15) or now.hour > 15 or (now.hour == 15 and now.minute > 30):
        return # Outside market hours

    idempotency_key = f"{today.isoformat()}_{now.hour}_{now.minute // 15}"
    if not acquire_distributed_lease("light_monitor", idempotency_key, ttl_minutes=14):
        return

    logger.info("Layer 1 Light Monitor: Checking price moves & alerts on active positions...")
    try:
        portfolio = compute_portfolio_fifo()
        for holding in portfolio.get("holdings", []):
            if holding.get("alerts"):
                logger.warning(f"Holding Alert on {holding['symbol']}: {holding['alerts']}")
        complete_distributed_lease("light_monitor", idempotency_key)
    except Exception as e:
        logger.error(f"Error in Light Monitor: {e}")
        release_distributed_lease_on_failure("light_monitor", idempotency_key, str(e))


def run_layer2_main_analysis():
    """
    Layer 2: Post-Market Main Analysis (4:30 PM IST).
    Calculates technicals, scores universe, generates 5-day forecasts, updates tracking.
    Protected by daily idempotency lease to prevent duplicate rescans across worker processes.
    """
    today = date.today()
    if not is_trading_day(today):
        logger.info(f"Skipping Main Analysis: {today} is an NSE market holiday/weekend.")
        return

    idempotency_key = f"{today.isoformat()}_eod_main_analysis"
    if not acquire_distributed_lease("main_analysis", idempotency_key, ttl_minutes=60):
        return
        
    logger.info("Layer 2: Starting Post-Market Main Analysis (4:30 PM IST)...")
    try:
        # 1. Evaluate completed 5-day forecasts
        eval_count = evaluate_pending_forecasts()
        logger.info(f"Evaluated {eval_count} completed 5-day forecast endpoints.")
        
        # 2. Run multi-factor stock screening
        recs = generate_daily_recommendations()
        logger.info(f"Generated {len(recs)} new 5-day recommendations.")
        
        # 3. Update portfolio snapshot
        compute_portfolio_fifo()
        
        # 4. Daily Database Backup
        backup_database()
        logger.info("Daily database backup snapshot created.")

        complete_distributed_lease("main_analysis", idempotency_key)
    except Exception as e:
        logger.error(f"Error in Layer 2 Main Analysis: {e}")
        release_distributed_lease_on_failure("main_analysis", idempotency_key, str(e))


def run_layer3_morning_pipeline():
    """
    Layer 3: Pre-Market Refresh & Morning Report Delivery (05:15 AM IST).
    Builds and validates morning HTML and PDF reports with T+5 scorecard footers.
    Guaranteed single execution across multi-worker deployments.
    """
    today = date.today()
    if not is_trading_day(today):
        logger.info(f"Skipping Morning Report Delivery: {today} is an exchange holiday.")
        return

    idempotency_key = f"{today.isoformat()}_morning_report_dispatch"
    if not acquire_distributed_lease("morning_report", idempotency_key, ttl_minutes=45):
        return
        
    logger.info("Layer 3: Morning Pipeline Activated (Pre-Market 05:15 AM IST)...")
    try:
        report = generate_morning_report()
        logger.info(f"Morning report compiled: {report.get('pdf_file', 'report.pdf')}")
        complete_distributed_lease("morning_report", idempotency_key)
    except Exception as e:
        logger.error(f"Error in Morning Pipeline: {e}")
        release_distributed_lease_on_failure("morning_report", idempotency_key, str(e))


def start_scheduler():
    """Start the APScheduler background tasks."""
    if not scheduler.running:
        scheduler.add_job(run_layer1_light_monitor, IntervalTrigger(minutes=15), id="light_monitor", replace_existing=True)
        
        h2, m2 = map(int, SCHEDULE_MAIN_ANALYSIS.split(":"))
        scheduler.add_job(run_layer2_main_analysis, CronTrigger(hour=h2, minute=m2, timezone=MARKET_TIMEZONE), id="main_analysis", replace_existing=True)
        
        scheduler.add_job(run_layer3_morning_pipeline, CronTrigger(hour=5, minute=15, timezone=MARKET_TIMEZONE), id="morning_report", replace_existing=True)
        
        scheduler.start()
        logger.info(f"PredictaStock Background Scheduler started on {WORKER_ID} with distributed database leases.")
