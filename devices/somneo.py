import logging
import asyncio
from datetime import datetime, timezone

from pysomneoctrl import SomneoDevice

from db import get_conn
from utils.asyncutil import run_in_executor

logger = logging.getLogger(__name__)

SENSOR_INTERVAL = 10
SENSOR_RETRY = 30


class SomneoHolder:
    def __init__(self, ip: str):
        self.ip = ip
        self._device = SomneoDevice(ip=ip)
        self._errors = 0
        self._max_errors = 3

    def _reload(self):
        logger.info("[SOMNEO] Reloading SomneoDevice...")
        self._device = SomneoDevice(ip=self.ip)
        self._errors = 0
        logger.info("[SOMNEO] Reload complete")

    def _record_error(self, e: Exception):
        self._errors += 1
        logger.warning(
            f"[SOMNEO] Error #{self._errors}: {type(e).__name__}: {e}", exc_info=True
        )
        if self._errors >= self._max_errors:
            self._reload()

    def __getattr__(self, name: str):
        attr = getattr(self._device, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            try:
                result = attr(*args, **kwargs)
                self._errors = 0  # reset on success
                return result
            except Exception as e:
                self._record_error(e)
                raise  # re-raise so callers still know it failed

        return wrapper


@run_in_executor
def bedlight(somneo: SomneoHolder, *args, **kwargs):
    for attempt in range(2):
        try:
            somneo.bedlight(*args, **kwargs)
            return
        except Exception as e:
            logger.warning(
                f"[BEDLIGHT] Attempt {attempt + 1} failed: {type(e).__name__}: {e}"
            )
            if attempt == 0:
                somneo._reload()
    logger.error("[BEDLIGHT] Failed after reload, giving up")


def _store_sensors(data: dict):
    """
    Map raw sensor keys to DB columns and insert a row.
    e.g.;
    {'mslux': 280.2, 'mstmp': 22, 'msrhu': 35.7, 'mssnd': 35, 'avlux': 627, 'avtmp': 22, 'avrhu': 36, 'avsnd': 30}
    """
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sensor_log (temperature, humidity, lux, lux_avg, sound, sound_avg, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                data.get("mstmp"),
                data.get("msrhu"),
                data.get("mslux"),
                data.get("avlux"),
                data.get("mssnd"),
                data.get("avsnd"),
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


async def track_sensors(somneo: SomneoHolder):
    """Poll Somneo sensors forever and persist to SQLite."""

    @run_in_executor
    def update_sensors():
        somneo.update_sensors()
        if somneo.sensor_data is None:
            raise RuntimeError("sensor_data is None")

    while True:
        try:
            await update_sensors()
            data = somneo.sensor_data
            _store_sensors(data)

            await asyncio.sleep(SENSOR_INTERVAL)

        except Exception as e:
            logger.warning(
                f"[SENSORS] Error reading sensors, retrying in {SENSOR_RETRY}s: {type(e).__name__}: {e}",
                exc_info=True,
            )
            somneo._record_error(
                e
            )  # explicitly drive the reload, it isnt always fired..
            await asyncio.sleep(SENSOR_RETRY)
