import json
import os
from dotenv import load_dotenv

load_dotenv()

# Somneo
SOMNEO_IP = os.environ["SOMNEO_IP"]
USB_LIGHT = os.getenv("USB_LIGHT", "false").lower() == "true"

# KAKU RF plugs
KAKU_ADDRESS = int(os.getenv("KAKU_ADDRESS", "12345678"))
KAKU_COFFEE_ADDRESS = int(os.getenv("KAKU_COFFEE_ADDRESS", "87654321"))
KAKU_UNITS = [
    int(u.strip()) for u in os.getenv("KAKU_UNITS", "").split(",") if u.strip()
]
KAKU_USE_GROUP = os.getenv("KAKU_USE_GROUP", "false").lower() == "true"
KAKU_COFFEE_UNIT = int(os.getenv("KAKU_COFFEE_UNIT", "2"))
KAKU_SENDOOK_PATH = os.getenv("KAKU_SENDOOK_PATH", "/home/casper/rpitx/sendook")
KAKU_PULSE_US = int(os.getenv("KAKU_PULSE_US", "275"))
KAKU_REPEATS = int(os.getenv("KAKU_REPEATS", "4"))
KAKU_PAIR_DURATION = int(os.getenv("KAKU_PAIR_DURATION", "15"))

# Google Calendar
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary")
GCAL_CREDENTIALS_FILE = os.getenv("GCAL_CREDENTIALS_FILE", "credentials.json")
GCAL_TOKEN_FILE = os.getenv("GCAL_TOKEN_FILE", "token.json")

# Discord bot
DISCORD_BOT_ENABLED = os.getenv("DISCORD_BOT_ENABLED", "false").lower() == "true"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_OWNER_ID = int(os.getenv("DISCORD_OWNER_ID", "0"))
DISCORD_MEMBER_ID = int(os.getenv("DISCORD_MEMBER_ID", "0")) or None
SLEEP_TARGET_HOUR = int(os.getenv("SLEEP_TARGET_HOUR", "23"))
SLEEP_DURATION_H = int(os.getenv("SLEEP_DURATION_H", "8"))
DISCORD_NUDGE_ADVANCE_MIN = int(os.getenv("DISCORD_NUDGE_ADVANCE_MIN", "20"))

# Config file (fallback schedule)
with open("config.json") as _f:
    _cfg = json.load(_f)

WINDDOWNS = _cfg.get("winddowns", [])
SUNRISES = _cfg.get("sunrises", [])
