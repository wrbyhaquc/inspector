"""Shrinking many frames read from a hard disk.

A hard disk is fast for one reader going through files in order and very slow for many readers at once (the head
keeps jumping: 31 parallel readers managed ~11 frames/s). So one thread reads the files in order and a few worker
processes decode + resize. The workers import only numpy and Pillow (not torch), so they start quickly."""
import concurrent.futures
import io
import os
import queue
import threading

import numpy as np
from PIL import Image


def decode_resize(raw, w, h):
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB").resize((w, h), Image.BOX), dtype=np.uint8)


def shrink_all(paths, w, h, workers=None, ahead=64):
    """Yield (index, array) for every path, in order. One reader thread, `workers` decoding processes,
    at most `ahead` frames read but not yet returned (memory bound)."""
    workers = workers or max(2, min(8, (os.cpu_count() or 4) - 2))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
        futs = queue.Queue()
        room = threading.Semaphore(ahead)
        failed = []

        def reader():
            try:
                for i, p in enumerate(paths):
                    room.acquire()
                    with open(p, "rb") as f:
                        raw = f.read()
                    futs.put((i, ex.submit(decode_resize, raw, w, h)))
            except Exception as e:                     # surfaced in the main thread
                failed.append(e)
            finally:
                futs.put(None)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        while True:
            item = futs.get()
            if item is None:
                break
            i, fut = item
            a = fut.result()
            room.release()
            yield i, a
        t.join()
        if failed:
            raise failed[0]
