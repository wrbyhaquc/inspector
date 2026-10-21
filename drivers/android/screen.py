"""A screenshot taken inside Android (adb screencap): always works, but every shot makes the device read back its
screen (~180 ms, slows the emulator down at high rates). Copying the window (drivers/windows.py) is the fast way."""
import struct
import subprocess

import numpy as np


def grab(adb, serial):
    """-> HxWx3 uint8 RGB array at the device's own size, or None."""
    r = subprocess.run([adb, "-s", serial, "exec-out", "screencap"], capture_output=True, timeout=10)
    data = r.stdout
    if len(data) < 16:
        return None
    w, h, fmt = struct.unpack_from("<III", data, 0)
    n = w * h * 4
    header = len(data) - n                       # 12 bytes on old Android, 16 with colorspace
    if header not in (12, 16) or fmt != 1:       # 1 = RGBA_8888
        return None
    img = np.frombuffer(data, dtype=np.uint8, count=n, offset=header).reshape(h, w, 4)
    return img[:, :, :3]
