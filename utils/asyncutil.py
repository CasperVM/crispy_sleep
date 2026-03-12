import asyncio
import functools


def run_in_executor(f=None, *, timeout=20):
    def decorator(func):
        @functools.wraps(func)
        async def inner(*args, **kwargs):
            loop = asyncio.get_running_loop()
            fut = loop.run_in_executor(None, lambda: func(*args, **kwargs))
            if timeout is None:
                return await fut
            return await asyncio.wait_for(fut, timeout)

        return inner

    if f is None:
        return decorator
    else:
        return decorator(f)
