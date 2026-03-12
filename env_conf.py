import json
import os
from dotenv import load_dotenv

load_dotenv()

# Somneo
SOMNEO_IP = os.environ["SOMNEO_IP"]
USB_LIGHT = os.getenv("USB_LIGHT", "false").lower() == "true"
KAKU_UNITS = [
    int(u.strip()) for u in os.getenv("KAKU_UNITS", "").split(",") if u.strip()
]

# Google Calendar
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary")
GCAL_CREDENTIALS_FILE = os.getenv("GCAL_CREDENTIALS_FILE", "credentials.json")
GCAL_TOKEN_FILE = os.getenv("GCAL_TOKEN_FILE", "token.json")

# Signal
SIGNAL_CLI_URL = os.getenv("SIGNAL_CLI_URL", "http://127.0.0.1:8080")
SIGNAL_PHONE = os.environ["SIGNAL_PHONE"]
SIGNAL_ALLOWED_SENDERS = [
    s.strip() for s in os.getenv("SIGNAL_ALLOWED_SENDERS", "").split(",") if s.strip()
]
SIGNAL_PREFIX = os.getenv("SIGNAL_PREFIX", ".")

# Config file (fallback schedule)
with open("config.json") as _f:
    _cfg = json.load(_f)

SIGNAL_BOT_ENABLED = _cfg.get("signal_bot_enabled", True)
WINDDOWNS = _cfg.get("winddowns", [])
SUNRISES = _cfg.get("sunrises", [])
