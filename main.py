#!/usr/bin/env python3
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from db import init_db, is_scheduling_enabled, get_conn
from devices.somneo import SomneoHolder, bedlight, track_sensors
from devices.usb_light_pi3 import blink_notify, usb_off, usb_on
from devices.kaku import plug_on, plug_off, plug_group_on, plug_group_off
from gcal import poll_gcal
from scheduler import get_next_event
from env_conf import SOMNEO_IP, USB_LIGHT, KAKU_UNITS, KAKU_USE_GROUP, KAKU_COFFEE_UNIT, KAKU_COFFEE_ADDRESS, KAKU_COFFEE_SENDS, KAKU_COFFEE_SEND_GAP, DISCORD_BOT_ENABLED, DISCORD_NUDGE_ADVANCE_MIN
from state import DispatcherState
from api import run_api

logger = logging.getLogger(__name__)

# Light routines


async def _kaku_on():
    if KAKU_USE_GROUP:
        await plug_group_on()
    else:
        for unit in KAKU_UNITS:
            await plug_on(unit)


async def _kaku_off():
    if KAKU_USE_GROUP:
        await plug_group_off()
    else:
        for unit in KAKU_UNITS:
            await plug_off(unit)


async def turn_off_somneo(somneo):
    await bedlight(somneo, False)


async def _check_abort(somneo, event_type: str = "") -> bool:
    """If scheduling was disabled or routine was cancelled mid-run, clean up and return True."""
    if not is_scheduling_enabled():
        await bedlight(somneo, False)
        if USB_LIGHT:
            await usb_off()
        await _kaku_off()
        return True
    if event_type:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (f"cancel_{event_type}",),
            ).fetchone()
            if row and row["value"] == "1":
                conn.execute("DELETE FROM settings WHERE key = ?", (f"cancel_{event_type}",))
                await bedlight(somneo, False)
                if USB_LIGHT:
                    await usb_off()
                await _kaku_off()
                logger.info(f"[ABORT] {event_type} cancelled mid-run")
                return True
    return False


async def winddown(somneo, start=20, end=0, duration_minutes=30, ctype=3):
    """Gradually dims Somneo from start → end brightness over duration_minutes."""
    steps = start - end
    if steps <= 0:
        logger.warning("winddown: start must be greater than end")
        return

    if USB_LIGHT:
        await blink_notify()
    await _kaku_on()

    # Turn on first.. might be wrong color initially? (BUG)
    await bedlight(somneo, True, brightness=1, ctype=ctype)
    await asyncio.sleep(10)

    step_time = (duration_minutes * 60) / steps
    logger.info(f"Wind-down: {start} → {end} over {duration_minutes} min")

    for current in range(start, end, -1):
        await bedlight(somneo, True, brightness=current, ctype=ctype)
        await asyncio.sleep(step_time)

        if current < 10 and USB_LIGHT:
            await usb_off()

        if await _check_abort(somneo, "winddown"):
            return

    await bedlight(somneo, False)
    if USB_LIGHT:
        await usb_off()
    await _kaku_off()
    logger.info("Wind-down complete.")


async def sunrise(somneo, start=0, end=25, duration_minutes=30, ctype=2):
    """Gradually brightens Somneo from start → end to simulate sunrise."""
    steps = end - start
    if steps <= 0:
        logger.warning("sunrise: end must be greater than start")
        return

    step_time = (duration_minutes * 60) / steps
    logger.info(f"Sunrise: {start} → {end} over {duration_minutes} min")

    for current in range(start, end + 1):
        await bedlight(somneo, True, brightness=current, ctype=ctype)
        await asyncio.sleep(step_time)

        if await _check_abort(somneo, "sunrise"):
            return

    if USB_LIGHT:
        await usb_on()
    await _kaku_on()
    logger.info("Sunrise complete.")


async def coffee(somneo=None, **_):
    """Turns on the coffee machine plug at the scheduled start time."""
    for i in range(KAKU_COFFEE_SENDS):
        await plug_on(KAKU_COFFEE_UNIT, address=KAKU_COFFEE_ADDRESS)
        if i < KAKU_COFFEE_SENDS - 1:
            await asyncio.sleep(KAKU_COFFEE_SEND_GAP)
    logger.info(f"Coffee: unit {KAKU_COFFEE_UNIT} on (address {KAKU_COFFEE_ADDRESS}, {KAKU_COFFEE_SENDS}x).")


# Dispatcher

ROUTINES = {"winddown": winddown, "sunrise": sunrise, "coffee": coffee}


async def event_dispatcher(somneo, notify_queue=None, state=None):
    """
    Every 30s, checks both event types for due events and fires them.
    Deduplicates by (event_type, trigger minute) so nothing fires twice.
    """
    fired: set[tuple[str, str]] = set()
    nudged: set[tuple[str, str]] = set()

    while True:
        # logger.info("Checking events")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        window_end = now + timedelta(seconds=30)
        nudge_window = timedelta(minutes=DISCORD_NUDGE_ADVANCE_MIN)

        for etype, fn in ROUTINES.items():
            ev = get_next_event(etype)
            if not ev:
                # logger.info("Skipping1")
                continue
            # print(ev)

            trigger_at = datetime.fromisoformat(ev["trigger_at"])

            # Nudge ahead of time
            if (
                notify_queue is not None
                and etype in ("winddown", "sunrise")
                and now < trigger_at <= now + nudge_window
            ):
                nudge_key = (etype, trigger_at.strftime("%Y-%m-%d %H:%M"))
                if nudge_key not in nudged:
                    nudged.add(nudge_key)
                    await notify_queue.put({"event_type": etype, "trigger_at": trigger_at})

            if trigger_at > window_end:
                # logger.info("Skipping2")
                continue

            key = (etype, trigger_at.strftime("%Y-%m-%d %H:%M"))
            if key in fired:
                # logger.info("Skipping3")
                continue

            # Snooze check
            if state is not None and now < state.snoozed_until.get(etype, datetime.min):
                continue

            # Cancel check
            if state is not None and key in state.cancelled:
                state.cancelled.discard(key)
                logger.info(f"[DISPATCHER] {etype} @ {trigger_at.strftime('%H:%M')} cancelled via Discord")
                continue

            fired.add(key)
            # Prune keys older than 2 h
            cutoff = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
            fired = {k for k in fired if k[1] >= cutoff}
            nudged = {k for k in nudged if k[1] >= cutoff}

            logger.info(
                f"[{ev['source'].upper()}] Firing {etype} @ {trigger_at.astimezone().strftime('%H:%M')}"
            )

            asyncio.create_task(
                fn(
                    somneo,
                    duration_minutes=int(ev.get("duration_minutes") or 30),
                    ctype=int(ev.get("ctype") or (3 if etype == "winddown" else 2)),
                )
            )

        await asyncio.sleep(15)


# Entry point


async def main():
    init_db()
    somneo = SomneoHolder(ip=SOMNEO_IP)
    logger.info("crispy_sleep 🌙 starting up")
    # await turn_off_somneo(somneo)

    state = DispatcherState()
    notify_queue: asyncio.Queue = asyncio.Queue()

    tasks = [
        track_sensors(somneo),
        poll_gcal(),
        event_dispatcher(somneo, notify_queue, state),
        run_api(somneo),
    ]

    if DISCORD_BOT_ENABLED:
        from discord_bot import run_discord_bot
        tasks.append(run_discord_bot(notify_queue, state, somneo, ROUTINES))

    await asyncio.gather(*tasks)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    asyncio.run(main())
