"""Atomic file writes: write a temp file next to the target, then os.replace it in.

Each writer gets its own temp name (process + thread), so two server threads saving the same file at once do not
share one; on Windows the replace fails while another process happens to have the target open, so it is retried
briefly. A failed write leaves the old file as it was and no temp file behind. Imports nothing of the platform, so
any module can use it."""
import json
import os
import threading
import time


def _write(path, put, **open_kw):
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", **open_kw) as f:
            put(f)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_text(path, text, **open_kw):
    _write(path, lambda f: f.write(text), **open_kw)


def write_json(path, obj, **dump_kw):
    """json.dump(obj, **dump_kw) into path, atomically."""
    _write(path, lambda f: json.dump(obj, f, **dump_kw))
