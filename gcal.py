from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from db import get_conn
from env_conf import (
    GCAL_CALENDAR_ID,
    GCAL_CREDENTIALS_FILE,
    GCAL_TOKEN_FILE,
    GCAL_SERVICE_ACCOUNT_FILE,
)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
POLL_INTERVAL = 300  # seconds
logger = logging.getLogger(__name__)

_WINDDOWN_KW = {"winddown", "wind down", "wind-down", "bedtime", "sleep"}
_SUNRISE_KW = {"sunrise", "wake", "wakeup", "wake up", "wake-up"}
_COFFEE_KW = {"coffee"}


def _classify(title: str) -> Optional[str]:
    t = title.lower()
    if any(k in t for k in _WINDDOWN_KW):
        return "winddown"
    if any(k in t for k in _SUNRISE_KW):
        return "sunrise"
    if any(k in t for k in _COFFEE_KW):
        return "coffee"
    return None


def _parse_description(desc: str) -> dict:
    """
    Optional ctype override in event description:
        ctype: 2
    """
    out = {}
    for line in (desc or "").splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            if k.strip().lower() == "ctype":
                out["ctype"] = int(v.strip())
    return out


def _duration_minutes(start_raw: str, end_raw: str) -> Optional[int]:
    try:
        start = datetime.fromisoformat(start_raw)
        end = datetime.fromisoformat(end_raw)
        return max(1, int((end - start).total_seconds() / 60))
    except Exception:
        return None


def _get_creds():
    if GCAL_SERVICE_ACCOUNT_FILE:
        return service_account.Credentials.from_service_account_file(
            GCAL_SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
    # OAuth2 flow
    creds = None
    token = Path(GCAL_TOKEN_FILE)
    if token.exists():
        creds = Credentials.from_authorized_user_file(token, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                GCAL_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        token.write_text(creds.to_json())
    return creds


def _sync_fetch():
    creds = _get_creds()
    svc = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    items = (
        svc.events()
        .list(
            calendarId=GCAL_CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=7)).isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )

    # Only process events we actually care about
    relevant = [ev for ev in items if _classify(ev.get("summary", ""))]
    fetched_ids = {ev["id"] for ev in relevant}

    with get_conn() as conn:
        # 1. Upsert everything returned by Google
        for ev in relevant:
            etype = _classify(ev["summary"])
            start_raw = ev["start"].get("dateTime") or ev["start"].get("date")
            end_raw = ev["end"].get("dateTime") or ev["end"].get("date")
            if not start_raw:
                continue

            # print(ev)
            trigger = datetime.fromisoformat(start_raw)
            trigger = trigger.astimezone(timezone.utc).replace(tzinfo=None)
            duration = _duration_minutes(start_raw, end_raw) if end_raw else None
            params = _parse_description(ev.get("description"))
            conn.execute(
                """
                INSERT INTO gcal_cache (gcal_id, event_type, trigger_at, duration_minutes, ctype, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(gcal_id) DO UPDATE SET
                    event_type=excluded.event_type,
                    trigger_at=excluded.trigger_at,
                    duration_minutes=excluded.duration_minutes,
                    ctype=excluded.ctype,
                    updated_at=excluded.updated_at
            """,
                (
                    ev["id"],
                    etype,
                    trigger.isoformat().replace("T", " "),
                    duration,
                    params.get("ctype"),
                ),
            )

        # 2. Delete future cached events that are no longer in Google Calendar
        cached_rows = conn.execute(
            "SELECT gcal_id FROM gcal_cache WHERE trigger_at >= ?",
            (now_str,),
        ).fetchall()
        stale_ids = [
            row["gcal_id"] for row in cached_rows if row["gcal_id"] not in fetched_ids
        ]
        if stale_ids:
            conn.executemany(
                "DELETE FROM gcal_cache WHERE gcal_id = ?",
                [(gid,) for gid in stale_ids],
            )
            # logger.info(f"GCal: removed {len(stale_ids)} deleted/cancelled event(s) from cache")

        # 3. Clean up anything in the past regardless
        conn.execute("DELETE FROM gcal_cache WHERE trigger_at < ?", (now_str,))

    logger.info(f"GCal: synced {len(relevant)} relevant event(s)")


async def poll_gcal():
    loop = asyncio.get_event_loop()
    while True:
        try:
            await loop.run_in_executor(None, _sync_fetch)
        except Exception as e:
            logger.error(f"GCal poll error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
