#!/usr/bin/env python3
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from db import init_db, is_scheduling_enabled
from devices.somneo import SomneoHolder, bedlight, track_sensors
from devices.usb_light_pi3 import blink_notify, usb_off, usb_on
from devices.kaku import plug_on, plug_off
from gcal import poll_gcal
from scheduler import get_next_event
from env_conf import SOMNEO_IP, USB_LIGHT, KAKU_UNITS
from api import run_api

logger = logging.getLogger(__name__)

# Light routines


async def turn_off_somneo(somneo):
    await bedlight(somneo, False)


async def _check_abort(somneo):
    """If scheduling was disabled mid-routine, kill everything and return True."""
    if not is_scheduling_enabled():
        await bedlight(somneo, False)
        if USB_LIGHT:
            await usb_off()
        for unit in KAKU_UNITS:
            await plug_off(unit)
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
    for unit in KAKU_UNITS:
        await plug_on(unit)

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

        if await _check_abort(somneo):
            return

    await bedlight(somneo, False)
    if USB_LIGHT:
        await usb_off()
    for unit in KAKU_UNITS:
        await plug_off(unit)
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

        if await _check_abort(somneo):
            return

    if USB_LIGHT:
        await usb_on()
    for unit in KAKU_UNITS:
        await plug_on(unit)
    logger.info("Sunrise complete.")


# Dispatcher

ROUTINES = {"winddown": winddown, "sunrise": sunrise}


async def event_dispatcher(somneo):
    """
    Every 30s, checks both event types for due events and fires them.
    Deduplicates by (event_type, trigger minute) so nothing fires twice.
    """
    fired: set[tuple[str, str]] = set()

    while True:
        # logger.info("Checking events")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        window_end = now + timedelta(seconds=30)

        for etype, fn in ROUTINES.items():
            ev = get_next_event(etype)
            if not ev:
                # logger.info("Skipping1")
                continue
            # print(ev)

            trigger_at = datetime.fromisoformat(ev["trigger_at"])
            if trigger_at > window_end:
                # logger.info("Skipping2")
                continue

            key = (etype, trigger_at.strftime("%Y-%m-%d %H:%M"))
            if key in fired:
                # logger.info("Skipping3")
                continue

            fired.add(key)
            # Prune keys older than 2 h
            cutoff = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
            fired = {k for k in fired if k[1] >= cutoff}

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

    tasks = [
        track_sensors(somneo),
        poll_gcal(),
        event_dispatcher(somneo),
        run_api(somneo),
    ]

    await asyncio.gather(*tasks)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    asyncio.run(main())
