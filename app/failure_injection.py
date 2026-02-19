import os
import time

_leak_holder = []

def apply_failure(mode: str):
    global _leak_holder

    if mode == "HIGH_LATENCY":
        time.sleep(5)

    elif mode == "CRASH":
        os._exit(1)

    elif mode == "MEMORY_LEAK":
        _leak_holder.extend([x for x in range(5_000_000)])

    elif mode == "CPU_SPIKE":
        while True:
            pass
