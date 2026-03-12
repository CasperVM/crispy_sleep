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

# Config file (fallback schedule)
with open("config.json") as _f:
    _cfg = json.load(_f)

WINDDOWNS = _cfg.get("winddowns", [])
SUNRISES = _cfg.get("sunrises", [])
