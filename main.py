#!/usr/bin/env python3
import asyncio
import sys
from pysomneoctrl import SomneoDevice
from devices.somneo import bedlight, track_sensors
from devices.usb_light_pi3 import blink_notify, usb_off, usb_on
from env_conf import *
from utils.dateutil import sleep_until_cron


async def winddown(somneo, start=20, end=0, duration_minutes=30, ctype=3):
    """
    Gradually dims the Somneo bedlight from start -> end brightness over duration.

    somneo: SomneoDevice instance
    start: starting brightness (int)
    end: final brightness (int, usually 0)
    duration_minutes: total time for dimming
    ctype: light type/color
    """
    if USB_LIGHT:
        await blink_notify()

    await bedlight(somneo, True, brightness=1, ctype=3)
    # Turn this on first, might be wrong color initially? (BUG)
    await asyncio.sleep(10)

    steps = start - end
    if steps <= 0:
        print("Start must be greater than end")
        return

    total_seconds = duration_minutes * 60
    step_time = total_seconds / steps  # seconds per brightness step

    print(f"Starting wind-down: {start} -> {end} over {duration_minutes} min")

    current = start
    while current > end:
        await bedlight(somneo, True, brightness=current, ctype=ctype)
        await asyncio.sleep(step_time)
        if current < 10:
            await usb_off()
        current -= 1

    # Turn off when done
    bedlight(somneo, False)
    print("Wind-down complete. Light off.")

    # turn off
    if USB_LIGHT:
        await usb_off()


async def sunrise(somneo, start=0, end=25, duration_minutes=30, ctype=2):
    """Gradually increases light to simulate sunrise."""
    await bedlight(somneo, True, brightness=start, ctype=ctype)
    steps = end - start
    step_time = (duration_minutes * 60) / steps

    print(f"Sunrise: {start} -> {end} over {duration_minutes} min")
    for current in range(start, end + 1):
        await bedlight(somneo, True, brightness=current, ctype=ctype)
        await asyncio.sleep(step_time)

    print("Sunrise complete.")
    if USB_LIGHT:
        await usb_on()


async def winddown_job(somneo, wd):
    """Runs forever, executing at each cron tick."""
    cron = wd["cron"]
    while True:
        await sleep_until_cron(cron)
        print(f"[WINDDOWN] Triggering {cron}")
        await winddown(
            somneo,
            duration_minutes=int(wd["durationInMinutes"]),
            ctype=int(wd["ctype"]),
        )


async def sunrise_job(somneo, sr):
    """Runs forever, executing at each cron tick."""
    cron = sr["cron"]
    while True:
        await sleep_until_cron(cron)
        print(f"[SUNRISE] Triggering {cron}")
        await sunrise(
            somneo,
            duration_minutes=int(sr["durationInMinutes"]),
            ctype=int(sr["ctype"]),
        )


async def schedule_winddowns(somneo):
    while True:
        for wd in WINDDOWNS:
            await sleep_until_cron(wd["cron"])
            await winddown(
                somneo,
                duration_minutes=int(wd["durationInMinutes"]),
                ctype=int(wd["ctype"]),
            )


async def schedule_sunrises(somneo):
    while True:
        for sr in SUNRISES:
            await sleep_until_cron(sr["cron"])
            await sunrise(
                somneo,
                duration_minutes=int(sr["durationInMinutes"]),
                ctype=int(sr["ctype"]),
            )


async def main():
    somneo = SomneoDevice(ip=SOMNEO_IP)

    tasks = [
        # asyncio.create_task(winddown(somneo, duration_minutes=45)),
        asyncio.create_task(track_sensors(somneo))
    ]

    for wd in WINDDOWNS:
        tasks.append(asyncio.create_task(winddown_job(somneo, wd)))
    for sr in SUNRISES:
        tasks.append(asyncio.create_task(sunrise_job(somneo, sr)))

    # FIXME; we don't care for now..
    # for sig in (signal.SIGINT, signal.SIGTERM):
    #     asyncio.get_event_loop().add_signal_handler(sig, lambda: asyncio.create_task(shutdown(tasks)))

    await asyncio.gather(*tasks)


async def shutdown(tasks):
    print("\n[!] Received shutdown signal. Cancelling tasks...")
    for t in tasks:
        t.cancel()  # FIXME; Doesnt work?
    await asyncio.gather(*tasks, return_exceptions=True)
    print("[!] Shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
