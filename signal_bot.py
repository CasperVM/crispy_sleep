"""
Signal bot via signal-cli HTTP daemon.

WIP NOT IN USE

Setup:
  signal-cli -u +YOURNUMBER register
  signal-cli -u +YOURNUMBER verify CODE
  signal-cli -u +YOURNUMBER daemon --http 127.0.0.1:8080

set SIGNAL_CLI_URL=http://127.0.0.1:8080 in .env
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from db import get_conn
from env_conf import SIGNAL_CLI_URL, SIGNAL_PHONE, SIGNAL_ALLOWED_SENDERS, SIGNAL_PREFIX

logger = logging.getLogger(__name__)
POLL_INTERVAL = 5  # seconds

# JSON-RPC helpers


async def _rpc(method: str, params: dict) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{SIGNAL_CLI_URL}/api/v1/rpc",
            json={"jsonrpc": "2.0", "method": method, "id": 1, "params": params},
        ) as r:
            return await r.json()


async def _send(recipient: str, text: str):
    await _rpc("send", {"recipient": [recipient], "message": text})


async def _receive() -> list[dict]:
    res = await _rpc("receive", {"account": SIGNAL_PHONE})
    return res.get("result", [])


# Command parsing


def _parse(text: str) -> Optional[dict]:
    t = text.strip()

    # Must start with prefix (e.g. ".")
    if not t.startswith(SIGNAL_PREFIX):
        return None
    t = t[len(SIGNAL_PREFIX) :].strip().lower()

    # .winddown now / .sunrise now
    if re.fullmatch(r"(winddown|wind.?down)\s+now", t):
        return {
            "cmd": "trigger",
            "event_type": "winddown",
            "trigger_at": datetime.now(),
        }
    if re.fullmatch(r"sunrise\s+now", t):
        return {"cmd": "trigger", "event_type": "sunrise", "trigger_at": datetime.now()}

    # .winddown at HH:MM [tomorrow] / .sunrise at HH:MM [tomorrow]
    m = re.fullmatch(
        r"(winddown|wind.?down|sunrise)\s+at\s+(\d{1,2}:\d{2})(\s+tomorrow)?", t
    )
    if m:
        etype = "winddown" if "wind" in m.group(1) else "sunrise"
        hm = datetime.strptime(m.group(2), "%H:%M")
        base = datetime.now().replace(
            hour=hm.hour, minute=hm.minute, second=0, microsecond=0
        )
        if m.group(3) or base <= datetime.now():
            base += timedelta(days=1)
        return {"cmd": "override", "event_type": etype, "trigger_at": base}

    # .cancel [winddown|sunrise] [tonight|tomorrow]
    m = re.fullmatch(
        r"cancel(?:\s+(winddown|wind.?down|sunrise))?(?:\s+(tonight|tomorrow))?", t
    )
    if m:
        raw = m.group(1)
        when = m.group(2) or "tonight"
        etype = ("winddown" if "wind" in raw else "sunrise") if raw else None
        d = (
            datetime.now().date()
            if when == "tonight"
            else (datetime.now() + timedelta(days=1)).date()
        )
        return {"cmd": "cancel", "event_type": etype, "cancel_date": d}

    if t == "sleep":
        return {"cmd": "log_sleep", "event": "sleep"}
    if t == "wake":
        return {"cmd": "log_sleep", "event": "wake"}

    if t in ("status", "?"):
        return {"cmd": "status"}
    if t == "help":
        return {"cmd": "help"}

    return None


# Command handling


def _handle(cmd: dict) -> str:
    from scheduler import get_next_event  # late import to avoid circular

    c = cmd["cmd"]

    if c in ("trigger", "override"):
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO overrides (event_type, trigger_at, status) VALUES (?, ?, 'pending')",
                (cmd["event_type"], cmd["trigger_at"].isoformat()),
            )
        when = "now" if c == "trigger" else f"at {cmd['trigger_at'].strftime('%H:%M')}"
        return f"Scheduled {cmd['event_type']} {when}"

    if c == "log_sleep":
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO sleep_log (phone, event) VALUES (?, ?)",
                (cmd["phone"], cmd["event"]),
            )
        return f"Logged {cmd['event']} at {datetime.now().strftime('%H:%M')}"

    if c == "cancel":
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO cancellations (event_type, cancel_date) VALUES (?, ?)",
                (cmd["event_type"], cmd["cancel_date"].isoformat()),
            )
        label = cmd["event_type"] or "all events"
        return f"Cancelled {label} for {cmd['cancel_date']}"

    if c == "status":
        lines = ["Next scheduled events:"]
        for etype in ("winddown", "sunrise"):
            ev = get_next_event(etype)
            if ev:
                dt = datetime.fromisoformat(ev["trigger_at"])
                lines.append(
                    f"  {etype}: {dt.strftime('%a %d %b %H:%M')} (via {ev['source']})"
                )
            else:
                lines.append(f"  {etype}: nothing scheduled")
        return "\n".join(lines)

    if c == "help":
        p = SIGNAL_PREFIX
        return (
            f"crispy_sleep commands (prefix: '{p}'):\n"
            f"  {p}winddown now\n"
            f"  {p}sunrise now\n"
            f"  {p}winddown at HH:MM [tomorrow]\n"
            f"  {p}sunrise at HH:MM [tomorrow]\n"
            f"  {p}cancel [winddown|sunrise] [tonight|tomorrow]\n"
            f"  {p}status\n"
            f"  {p}sleep: log that you're going to sleep\n"
            f"  {p}wake: log that you woke up"
        )

    return f"Unknown command. Send '{SIGNAL_PREFIX}help' for options."


# Main bot loop


async def run_signal_bot():
    logger.info(f"Signal bot started (prefix: '{SIGNAL_PREFIX}')")
    while True:
        try:
            for msg in await _receive():
                env = msg.get("envelope", {})
                body = (env.get("dataMessage") or {}).get("message", "")
                sender = env.get("source", "")

                if not body or sender not in SIGNAL_ALLOWED_SENDERS:
                    continue

                # Silently ignore messages that don't start with the prefix
                if not body.strip().startswith(SIGNAL_PREFIX):
                    continue

                cmd = _parse(body)
                if cmd and "event" in cmd:
                    cmd["phone"] = sender
                reply = (
                    _handle(cmd)
                    if cmd
                    else f"Unknown command. Send '{SIGNAL_PREFIX}help'."
                )
                await _send(sender, reply)
                logger.info(f"Signal {sender}: {body!r} → {reply[:60]!r}")
        except Exception as e:
            logger.error(f"Signal bot error: {e}")
        await asyncio.sleep(POLL_INTERVAL)
