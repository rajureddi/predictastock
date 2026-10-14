"""
NSE Trading Calendar & Holiday Validator
Accurately accounts for weekends, official Indian exchange holidays, and special Muhurat trading sessions.
Complies with Section 7.4 (Exact Five-Day Rule) and Section 8.3 (Trading Days Only).
"""
from datetime import date, datetime, timedelta
from typing import List

# Official NSE Holidays for 2024, 2025, 2026 (YYYY-MM-DD)
NSE_HOLIDAYS = {
    # 2024
    date(2024, 1, 22),   # Special Holiday
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 8),    # Maha Shivratri
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 11),   # Id-Ul-Fitr
    date(2024, 4, 17),   # Shri Ram Navami
    date(2024, 5, 1),    # Maharashtra Day
    date(2024, 5, 20),   # Parliamentary Elections
    date(2024, 6, 17),   # Bakri Id
    date(2024, 7, 17),   # Muharram
    date(2024, 8, 15),   # Independence Day
    date(2024, 10, 2),   # Mahatma Gandhi Jayanti
    date(2024, 11, 1),   # Diwali Laxmi Pujan (Muhurat Trading only)
    date(2024, 11, 15),  # Gurunanak Jayanti
    date(2024, 11, 20),  # Maharashtra Assembly Elections
    date(2024, 12, 25),  # Christmas
    
    # 2025
    date(2025, 2, 26),   # Maha Shivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr
    date(2025, 4, 10),   # Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 6, 7),    # Bakri Id
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali (Laxmi Pujan)
    date(2025, 10, 22),  # Diwali Balipratipada
    date(2025, 11, 5),   # Prakash Gurpurb
    date(2025, 12, 25),  # Christmas

    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 16),   # Maha Shivratri
    date(2026, 3, 4),    # Holi
    date(2026, 3, 20),   # Id-Ul-Fitr
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Bakri Id
    date(2026, 8, 15),   # Independence Day
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 8),   # Diwali Laxmi Pujan
    date(2026, 11, 9),   # Diwali Balipratipada
    date(2026, 11, 24),  # Gurunanak Jayanti
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(d: date) -> bool:
    """Check if a given calendar date is an active NSE trading day (skipping weekends & holidays)."""
    # Saturday (5) or Sunday (6)
    if d.weekday() >= 5:
        return False
    # Holiday check
    if d in NSE_HOLIDAYS:
        return False
    return True


def get_next_trading_day(start_date: date) -> date:
    """Find the next valid NSE trading day strictly after start_date."""
    curr = start_date + timedelta(days=1)
    while not is_trading_day(curr):
        curr += timedelta(days=1)
    return curr


def get_nth_trading_day(start_date: date, n: int) -> date:
    """
    Implements Section 7.4 (Exact Five-Day Rule):
    Day 1 is start_date (if start_date is a trading day, otherwise next trading day).
    Finds the n-th trading day closing session endpoint.
    """
    curr = start_date if is_trading_day(start_date) else get_next_trading_day(start_date)
    count = 1
    while count < n:
        curr = get_next_trading_day(curr)
        count += 1
    return curr


def get_trading_days_between(start_date: date, end_date: date) -> List[date]:
    """Return all valid trading days in range [start_date, end_date] inclusive."""
    days = []
    curr = start_date
    while curr <= end_date:
        if is_trading_day(curr):
            days.append(curr)
        curr += timedelta(days=1)
    return days
