import asyncio
import subprocess

from utils.asyncutil import run_in_executor

"""
Horrible subprocess module that's really ugly;

But works for this simple task :)
"""

USB_DRIVER_PATH = "/sys/bus/usb/drivers/usb"
DEVICE = "1-1"


@run_in_executor
def run_tee(target: str, device: str):
    """Write the device name to a sysfs control file using sudo tee."""
    subprocess.run(
        ["sudo", "tee", target],
        input=f"{device}\n".encode(),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def usb_on():
    """bind usb"""
    try:
        bind_path = f"{USB_DRIVER_PATH}/bind"
        await run_tee(bind_path, DEVICE)
    except:
        pass  # might occur if already on


async def usb_off():
    try:
        unbind_path = f"{USB_DRIVER_PATH}/unbind"
        await run_tee(unbind_path, DEVICE)
    except:
        pass  # might occur if already off


async def blink_notify():
    await usb_on()
    await asyncio.sleep(1)
    await usb_off()
    await asyncio.sleep(1)
    await usb_on()
