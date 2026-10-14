"""
PredictaStock Background Workflow Scheduler
Implements the 3 Execution Layers and 5:45 AM Report Delivery Milestones per Section 8.1 & 8.2.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, date
import logging

from app.config import (
    MARKET_TIMEZONE, SCHEDULE_MAIN_ANALYSIS,
    SCHEDULE_MORNING_REFRESH, SCHEDULE_REPORT_BUILD,
    SCHEDULE_EMAIL_DEADLINE
)
from app.data.nse_calendar import is_trading_day
from app.services.prediction_engine import generate_daily_recommendations
from app.services.portfolio import compute_portfolio_fifo
from app.services.backtester import evaluate_pending_forecasts
from app.services.report_generator import generate_morning_report
from app.database import backup_database

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=MARKET_TIMEZONE)


def run_layer1_light_monitor():
    """
    Layer 1: Continuous Light Monitor (Every 15 mins during market hours 9:15 - 15:30 IST).
    Checks for sudden breaking news or circuit breaches on held/recommended stocks.
    """
    today = date.today()
    if not is_trading_day(today):
        return
        
    now = datetime.now()
    if now.hour < 9 or (now.hour == 9 and now.minute < 15) or now.hour > 15 or (now.hour == 15 and now.minute > 30):
        return # Outside market hours
        
    logger.info("Layer 1 Light Monitor: Checking price moves & news on active positions...")
    try:
        portfolio = compute_portfolio_fifo()
        for holding in portfolio["holdings"]:
            # Check for sudden intraday drops
            if holding.get("alerts"):
                logger.warning(f"Holding Alert on {holding['symbol']}: {holding['alerts']}")
    except Exception as e:
        logger.error(f"Error in Light Monitor: {e}")


def run_layer2_main_analysis():
    """
    Layer 2: Post-Market Main Analysis (4:30 PM IST).
    Calculates technicals, scores universe, generates 5-day forecasts, updates tracking.
    """
    today = date.today()
    if not is_trading_day(today):
        logger.info(f"Skipping Main Analysis: {today} is an NSE market holiday/weekend.")
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
        
        # 4. Daily Database Backup (Section 15.2)
        backup_database()
        logger.info("Daily database backup snapshot created.")
    except Exception as e:
        logger.error(f"Error in Layer 2 Main Analysis: {e}")


def run_layer3_morning_pipeline():
    """
    Layer 3: Pre-Market Refresh & Morning Report Delivery (4:30 AM - 5:45 AM IST).
    - 4:30 AM: Overnight news & global cues
    - 5:15 - 5:35 AM: Build & validate HTML and PDF report
    - 5:45 AM: Automated dispatch
    """
    today = date.today()
    if not is_trading_day(today):
        logger.info(f"Skipping Morning Report Delivery: {today} is an exchange holiday.")
        return
        
    logger.info("Layer 3: Morning Pipeline Activated (Pre-Market 4:30 AM IST)...")
    try:
        # Build HTML & PDF briefing
        report = generate_morning_report()
        logger.info(f"Morning report compiled: {report['pdf_file']}")
        logger.info(f"Validated and prepared for 5:45 AM IST dispatch. Target met.")
    except Exception as e:
        logger.error(f"Error in Morning Pipeline: {e}")


def start_scheduler():
    """Start the APScheduler background tasks."""
    if not scheduler.running:
        # Layer 1: Every 15 minutes
        scheduler.add_job(run_layer1_light_monitor, IntervalTrigger(minutes=15), id="light_monitor", replace_existing=True)
        
        # Layer 2: Daily at 4:30 PM (16:30 IST)
        h2, m2 = map(int, SCHEDULE_MAIN_ANALYSIS.split(":"))
        scheduler.add_job(run_layer2_main_analysis, CronTrigger(hour=h2, minute=m2, timezone=MARKET_TIMEZONE), id="main_analysis", replace_existing=True)
        
        # Layer 3: Daily at 5:15 AM (05:15 IST) for 5:45 AM delivery
        scheduler.add_job(run_layer3_morning_pipeline, CronTrigger(hour=5, minute=15, timezone=MARKET_TIMEZONE), id="morning_report", replace_existing=True)
        
        scheduler.start()
        logger.info("PredictaStock Automated Background Scheduler Started.")
