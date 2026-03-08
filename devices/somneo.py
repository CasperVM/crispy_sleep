import logging
import asyncio
from datetime import datetime, timezone

from pysomneoctrl import SomneoDevice

from db import get_conn
from utils.asyncutil import run_in_executor

logger = logging.getLogger(__name__)

SENSOR_INTERVAL = 10
SENSOR_RETRY = 30


@run_in_executor
def bedlight(somneo: SomneoDevice, *args, **kwargs):
    somneo.bedlight(*args, **kwargs)


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


async def track_sensors(somneo: SomneoDevice):
    """Poll Somneo sensors forever and persist to SQLite."""

    @run_in_executor
    def update_sensors():
        somneo.update_sensors()

    while True:
        try:
            await update_sensors()
            data = somneo.sensor_data
            _store_sensors(data)

            await asyncio.sleep(SENSOR_INTERVAL)

        except Exception as e:
            logger.warning(
                f"[SENSORS] Error reading sensors, retrying in {SENSOR_RETRY}s: {e}"
            )
            await asyncio.sleep(SENSOR_RETRY)
