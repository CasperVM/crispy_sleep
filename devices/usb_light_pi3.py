import subprocess

from utils.asyncutil import run_in_executor

HUB = "1-1"
PORT = "2"


@run_in_executor
def _uhubctl(action: str):
    subprocess.run(
        ["sudo", "uhubctl", "-l", HUB, "-p", PORT, "-a", action],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def usb_on():
    try:
        await _uhubctl("on")
    except Exception:
        pass


async def usb_off():
    try:
        await _uhubctl("off")
    except Exception:
        pass
