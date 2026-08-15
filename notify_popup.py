"""
Local alert: loud repeated beeps + an always-on-top popup box.

This is launched as its own detached process by check_jobs.py so it keeps
running (and stays visible on screen) even after the checker script exits.
Windows only (uses winsound + ctypes MessageBoxW).
"""

import sys
import threading
import time

try:
    import winsound
except ImportError:
    winsound = None

import ctypes

MB_OK = 0x0
MB_ICONINFORMATION = 0x40
MB_SYSTEMMODAL = 0x1000
MB_TOPMOST = 0x40000


def beep_loop():
    if not winsound:
        return
    for _ in range(8):
        try:
            winsound.Beep(1000, 400)
        except Exception:
            break
        time.sleep(0.15)


def main():
    message = sys.argv[1] if len(sys.argv) > 1 else "New Amazon warehouse job available!"

    t = threading.Thread(target=beep_loop, daemon=True)
    t.start()

    ctypes.windll.user32.MessageBoxW(
        0,
        message,
        "Amazon Warehouse Job Alert",
        MB_OK | MB_ICONINFORMATION | MB_SYSTEMMODAL | MB_TOPMOST,
    )


if __name__ == "__main__":
    main()
