"""
KAKU (KlikAanKlikUit) APA3-1500R RF plug controller.
Transmits at 433.92 MHz via rpitx sendook.
One-way fire-and-forget - no acknowledgement from plugs.

Configurable via environment variables:
  KAKU_ADDRESS      26-bit address shared across plugs (default: 12345678)
  KAKU_PULSE_US     Pulse width in microseconds (default: 275)
  KAKU_REPEATS      Frame repetitions per send (default: 4)
  KAKU_SENDOOK_PATH Path to rpitx sendook binary (default: /home/casper/rpitx/sendook)
  KAKU_PAIR_DURATION Seconds to keep sending during pairing (default: 15)

CLI usage:
  python3 devices/kaku.py on <unit>
  python3 devices/kaku.py off <unit>
  python3 devices/kaku.py groupon
  python3 devices/kaku.py groupoff
  python3 devices/kaku.py pair <unit>       # keep sending ON - replug device during window
  python3 devices/kaku.py unpair <unit>     # keep sending OFF - replug device during window
  python3 devices/kaku.py wipe              # GROUP OFF - clears all paired units on address

  Optional flags: --address <int>  --duration <seconds>
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time

# Allow running directly from project root or from devices/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.asyncutil import run_in_executor
from env_conf import (
    KAKU_ADDRESS as ADDRESS,
    KAKU_SENDOOK_PATH as SENDOOK_PATH,
    KAKU_PULSE_US as T,
    KAKU_REPEATS as REPEATS,
    KAKU_PAIR_DURATION as PAIR_DURATION,
)

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()  # serialises all RF transmissions; rpitx needs ≥1s between sends

_FREQ = "433920000"


# Encoding


def _encode_frame(address: int, unit: int, on: bool, group: bool = False) -> str:
    # Start pulse: 1T high, 9T low
    bits = [1] + [0] * 9
    # 32 data bits: 26 address + 1 group + 1 on/off + 4 unit
    data = []
    for i in range(25, -1, -1):
        data.append((address >> i) & 1)
    data.append(1 if group else 0)
    data.append(1 if on else 0)
    for i in range(3, -1, -1):
        data.append((unit >> i) & 1)
    for bit in data:
        bits += [1, 0, 1, 0, 0, 0] if bit == 0 else [1, 0, 0, 0, 1, 0]
    # Stop pulse
    bits += [1] + [0] * 40
    return "".join(str(b) for b in bits)


# Transmission


@run_in_executor
def _send(address: int, unit: int, on: bool, group: bool = False):
    """Single transmission + 1s cooldown. Runs in executor (blocking)."""
    label = ("GROUP " if group else "") + ("ON" if on else "OFF")
    logger.info(f"[KAKU] {label} address={address} unit={unit}")
    subprocess.run(
        [
            "sudo",
            SENDOOK_PATH,
            "-f",
            _FREQ,
            "-0",
            str(T),
            "-1",
            str(T),
            "-r",
            str(REPEATS),
            _encode_frame(address, unit, on, group),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


# Normal control


async def _send_exclusive(address: int, unit: int, on: bool, group: bool = False):
    async with _lock:
        await _send(address, unit, on, group)


async def plug_on(unit: int, address: int = ADDRESS):
    await _send_exclusive(address, unit, on=True)


async def plug_off(unit: int, address: int = ADDRESS):
    await _send_exclusive(address, unit, on=False)


async def plug_group_on(address: int = ADDRESS):
    await _send_exclusive(address, 0, on=True, group=True)


async def plug_group_off(address: int = ADDRESS):
    await _send_exclusive(address, 0, on=False, group=True)


# Pairing


async def pair(unit: int, address: int = ADDRESS, duration: int = PAIR_DURATION):
    """Register: sends ON repeatedly for `duration` seconds. Replug device during this window."""
    print(
        f"Pairing unit={unit} address={address} - replug device now ({duration}s window)"
    )
    end = time.monotonic() + duration
    while time.monotonic() < end:
        await _send_exclusive(address, unit, on=True)
    print("Pairing window closed.")


async def unpair(unit: int, address: int = ADDRESS, duration: int = PAIR_DURATION):
    """Deregister: sends OFF repeatedly for `duration` seconds. Replug device during this window."""
    print(
        f"Unpairing unit={unit} address={address} - replug device now ({duration}s window)"
    )
    end = time.monotonic() + duration
    while time.monotonic() < end:
        await _send_exclusive(address, unit, on=False)
    print("Unpairing window closed.")


async def wipe(address: int = ADDRESS, duration: int = PAIR_DURATION):
    """Wipe: sends GROUP OFF repeatedly. Clears all units paired to this address."""
    print(
        f"Wiping all units on address={address} - replug device now ({duration}s window)"
    )
    end = time.monotonic() + duration
    while time.monotonic() < end:
        await _send_exclusive(address, 0, on=False, group=True)
    print("Wipe window closed.")


# CLI


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)  # suppress INFO noise in CLI

    parser = argparse.ArgumentParser(description="KAKU RF plug controller")
    parser.add_argument(
        "command",
        choices=["on", "off", "groupon", "groupoff", "pair", "unpair", "wipe"],
    )
    parser.add_argument(
        "unit", type=int, nargs="?", default=0, help="Unit (channel) 0-15"
    )
    parser.add_argument(
        "--address",
        type=int,
        default=ADDRESS,
        help=f"26-bit address (default: {ADDRESS})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=PAIR_DURATION,
        help=f"Pairing window in seconds (default: {PAIR_DURATION})",
    )
    args = parser.parse_args()

    cmd = args.command
    if cmd in ("pair", "unpair", "wipe") and args.unit == 0 and cmd != "wipe":
        # Warn if user forgot to specify unit for pair/unpair
        if len(sys.argv) < 3 or not sys.argv[2].lstrip("-").isdigit():
            print("Warning: no unit specified, defaulting to unit=0")

    coros = {
        "on": lambda: plug_on(args.unit, args.address),
        "off": lambda: plug_off(args.unit, args.address),
        "groupon": lambda: plug_group_on(args.address),
        "groupoff": lambda: plug_group_off(args.address),
        "pair": lambda: pair(args.unit, args.address, args.duration),
        "unpair": lambda: unpair(args.unit, args.address, args.duration),
        "wipe": lambda: wipe(args.address, args.duration),
    }

    asyncio.run(coros[cmd]())
