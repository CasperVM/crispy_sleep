from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional
import logging
from cronsim import CronSim

from db import get_conn, is_scheduling_enabled
from env_conf import WINDDOWNS, SUNRISES

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Helsinki")
DEFAULTS = {
    "winddown": {"duration_minutes": 30, "ctype": 1},
    "sunrise": {"duration_minutes": 30, "ctype": 2},
    "coffee": {"duration_minutes": 1, "ctype": None},
}


def _next_gcal_event(event_type: str) -> Optional[dict]:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat().replace("T", " ")
    # logger.info(f"getting gcal ev: type={event_type} now={now}")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM gcal_cache
            WHERE event_type = ? AND trigger_at > ?
            ORDER BY trigger_at ASC LIMIT 1
        """,
            (event_type, now),
        ).fetchone()
    if not row:
        # logger.info("No gcal evs")
        return None
    ev = dict(row)
    # logger.info(f"Found gcal ev: {ev}")
    ev.setdefault("duration_minutes", DEFAULTS[event_type]["duration_minutes"])
    ev.setdefault("ctype", DEFAULTS[event_type]["ctype"])
    return {**ev, "source": "gcal"}


def _next_cron_event(event_type: str) -> Optional[dict]:
    configs = WINDDOWNS if event_type == "winddown" else SUNRISES
    if not configs:
        return None

    # Work in local time for cron simulation
    now_local = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    now_str = now_local.isoformat().replace("T", " ")

    best_dt, best_conf = None, None
    for conf in configs:
        nxt = next(CronSim(conf["cron"], now_str))  # returns naive local time
        if best_dt is None or nxt < best_dt:
            best_dt, best_conf = nxt, conf

    if not best_dt:
        return None

    # Convert the naive local cron result → UTC
    best_dt_local = best_dt.replace(tzinfo=LOCAL_TZ)
    best_dt_utc = best_dt_local.astimezone(timezone.utc).replace(tzinfo=None)

    return {
        "event_type": event_type,
        "trigger_at": best_dt_utc.isoformat(),
        "duration_minutes": int(best_conf["durationInMinutes"]),
        "ctype": int(best_conf["ctype"]),
        "source": "config",
    }


def get_next_event(event_type: str) -> Optional[dict]:
    """Returns the next event for event_type, honouring priority: gcal > config."""
    if not is_scheduling_enabled():
        return None
    return _next_gcal_event(event_type) or _next_cron_event(event_type)
