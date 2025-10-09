from datetime import datetime
import time
from pysomneoctrl import SomneoDevice

from utils.asyncutil import run_in_executor

# TODO: rewrite pysomneoctrl to contain async as well?
# - maybe new project + git submod?
# - both interfaces: blocking, non-blocking...


@run_in_executor
def bedlight(somneo: SomneoDevice, *args, **kwargs):
    somneo.bedlight(*args, **kwargs)


async def track_sensors(somneo: SomneoDevice):
    """Poll sensor data forever (for Grafana etc.)"""

    @run_in_executor
    def run():
        while True:
            try:
                somneo.update_sensors()
                data = somneo.sensor_data
                logline = f"[SENSORS] {datetime.now()} => {data}\n"
                print(logline, end="")

                # For now I guess we just dump to a log txt.
                with open("log.txt", "a") as f:
                    f.write(logline)
                # TODO: push to Psql...
            except Exception as e:
                print(f"[SENSORS] Error: {e}")
            time.sleep(10)  # TODO add interval.

    await run()
