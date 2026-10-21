"""Send actions to devices through the project's device driver (drivers/), in the project's coordinate space.

Each device has its own command lane (one thread, commands in order): a slow or stuck call never stalls the
watch loop, and never delays another device's commands."""
import concurrent.futures

import drivers
from i18n import _


class Executor:
    def __init__(self):
        self.lanes = {}                   # device name -> its own single-thread queue (commands stay in order)

    def submit(self, name, kind, **p):
        """kind: tap (x, y) | long_press (x, y, ms) | swipe (x1, y1, x2, y2, ms) | back | launch (package: start the
        app, or bring it to the front if it is running) | text (text: typed into the focused text box).
        Returns a Future (fails when the driver cannot do it)."""
        if kind not in drivers.CAPS or kind in ("screen", "touch_watch"):
            raise ValueError(kind)
        drv = drivers.current()
        lane = self.lanes.get(name)
        if lane is None:
            lane = self.lanes[name] = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"out-{name}")
        if kind not in drv.caps_of(name):
            from drivers import sources
            f = concurrent.futures.Future()
            f.set_exception(drivers.NotSupported(_("「{p1}」不能{p2}", p1=sources.label(name), p2=drivers.CAPS[kind])))
            return f
        return lane.submit(drv.input, name, kind, **p)
