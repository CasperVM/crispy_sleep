import datetime

from datetime import datetime
from dateutil import tz
from cronsim import CronSim
import asyncio


def seconds_until(target_time_str: str) -> float:
    """Return seconds until next occurrence of HH:MM (24h)."""
    now = datetime.now()
    target = datetime.strptime(target_time_str, "%H:%M").time()
    target_dt = datetime.combine(now.date(), target)
    if target_dt <= now:
        target_dt += datetime.timedelta(days=1)  # next day
    return (target_dt - now).total_seconds()


def next_from_cron(cron_expr: str) -> datetime:
    """
    Return next datetime (with local timezone) matching the cron expression.
    """
    now = datetime.now(tz=tz.tzlocal())
    sim = CronSim(cron_expr, now)
    next_time = next(sim)
    return next_time


async def sleep_until_cron(cron_expr: str):
    """Sleep until the next cron match."""
    next_time = next_from_cron(cron_expr)
    delta = (next_time - datetime.now(tz=tz.tzlocal())).total_seconds()
    print(
        f"[i] Sleeping until {next_time.strftime('%Y-%m-%d %H:%M:%S')} ({delta / 60:.1f} min)"
    )
    await asyncio.sleep(max(0, delta))
