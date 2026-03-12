import json
import os
from dotenv import load_dotenv

load_dotenv()

# Somneo
SOMNEO_IP = os.environ["SOMNEO_IP"]
USB_LIGHT = os.getenv("USB_LIGHT", "false").lower() == "true"

# KAKU RF plugs
KAKU_ADDRESS = int(os.getenv("KAKU_ADDRESS", "12345678"))
KAKU_UNITS = [int(u.strip()) for u in os.getenv("KAKU_UNITS", "").split(",") if u.strip()]
KAKU_USE_GROUP = os.getenv("KAKU_USE_GROUP", "false").lower() == "true"
KAKU_SENDOOK_PATH = os.getenv("KAKU_SENDOOK_PATH", "/home/casper/rpitx/sendook")
KAKU_PULSE_US = int(os.getenv("KAKU_PULSE_US", "275"))
KAKU_REPEATS = int(os.getenv("KAKU_REPEATS", "4"))
KAKU_PAIR_DURATION = int(os.getenv("KAKU_PAIR_DURATION", "15"))

# Google Calendar
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary")
GCAL_CREDENTIALS_FILE = os.getenv("GCAL_CREDENTIALS_FILE", "credentials.json")
GCAL_TOKEN_FILE = os.getenv("GCAL_TOKEN_FILE", "token.json")

# Config file (fallback schedule)
with open("config.json") as _f:
    _cfg = json.load(_f)

WINDDOWNS = _cfg.get("winddowns", [])
SUNRISES = _cfg.get("sunrises", [])
