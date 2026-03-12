"""
Small REST API for Grafana control panels.
Runs on port 8091 alongside the main app.
"""

from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from db import get_conn, cancel_todays_events
from devices.somneo import bedlight
from devices.usb_light_pi3 import usb_on, usb_off
from devices.kaku import plug_on, plug_off, plug_group_on, plug_group_off
from env_conf import USB_LIGHT

logger = logging.getLogger(__name__)
API_PORT = 8091

_somneo = None  # set on startup


def _cors(response: web.Response) -> web.Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# Light


async def handle_light_set(request: web.Request) -> web.Response:
    data = await request.json()
    brightness = int(data.get("brightness", 10))
    ctype = int(data.get("ctype", 3))

    brightness = max(0, min(25, brightness))
    # cancel_todays_events()

    if brightness == 0:
        await bedlight(_somneo, False)
        logger.info("[API] Light off (manual)")
    else:
        # Turn this on first, might be wrong color initially? (BUG)
        await bedlight(_somneo, True, brightness=1, ctype=ctype)
        await asyncio.sleep(1)
        await bedlight(_somneo, True, brightness=brightness, ctype=ctype)
        logger.info(f"[API] Light set brightness={brightness} ctype={ctype}")

    return _cors(web.json_response({"ok": True}))


async def handle_light_off(request: web.Request) -> web.Response:
    # cancel_todays_events()
    await bedlight(_somneo, False)
    if USB_LIGHT:
        await usb_off()
    logger.info("[API] Light off (manual)")
    return _cors(web.json_response({"ok": True}))


# Plugs


async def handle_plug(request: web.Request) -> web.Response:
    data = await request.json()
    unit = int(data.get("unit", 0))
    action = data.get("action", "on")

    if action == "on":
        await plug_on(unit)
    elif action == "off":
        await plug_off(unit)
    elif action == "groupon":
        await plug_group_on()
    elif action == "groupoff":
        await plug_group_off()
    else:
        return _cors(
            web.json_response({"ok": False, "error": "unknown action"}, status=400)
        )

    logger.info(f"[API] Plug action={action} unit={unit}")
    return _cors(web.json_response({"ok": True}))


# Scheduling toggle


async def handle_scheduling_enable(request: web.Request) -> web.Response:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('scheduling_enabled', '1')"
        )
    logger.info("[API] Scheduling enabled")
    return _cors(web.json_response({"ok": True, "scheduling_enabled": True}))


async def handle_scheduling_disable(request: web.Request) -> web.Response:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('scheduling_enabled', '0')"
        )
    logger.info("[API] Scheduling disabled")
    return _cors(web.json_response({"ok": True, "scheduling_enabled": False}))


async def handle_scheduling_status(request: web.Request) -> web.Response:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'scheduling_enabled'"
        ).fetchone()
    enabled = (row["value"] == "1") if row else True
    return _cors(web.json_response({"scheduling_enabled": enabled}))


# CORS preflight


async def handle_options(request: web.Request) -> web.Response:
    return web.Response(
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        }
    )


# Startup


async def run_api(somneo):
    global _somneo
    _somneo = somneo

    app = web.Application()
    app.router.add_post("/api/light", handle_light_set)
    app.router.add_post("/api/light/off", handle_light_off)
    app.router.add_post("/api/plug", handle_plug)
    app.router.add_post("/api/scheduling/enable", handle_scheduling_enable)
    app.router.add_post("/api/scheduling/disable", handle_scheduling_disable)
    app.router.add_get("/api/scheduling/status", handle_scheduling_status)
    app.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    await site.start()
    logger.info(f"API listening on port {API_PORT}")
