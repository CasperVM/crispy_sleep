import os
from typing import Literal
from dotenv import load_dotenv
import json

load_dotenv()

CONFIG_JSON = None

with open("config.json") as f:
    CONFIG_JSON = json.loads("\n".join(f.readlines()))

gradient_keys = Literal["cron", "durationInMinutes", "ctype"]

SOMNEO_IP: str = os.getenv("SOMNEO_IP")

USB_LIGHT: bool = CONFIG_JSON["USB_LIGHT"]
WINDDOWNS: list[dict[gradient_keys, str]] = CONFIG_JSON["WINDDOWNS"]
SUNRISES: list[dict[gradient_keys, str]] = CONFIG_JSON["SUNRISES"]
