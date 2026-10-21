"""How a source's own picture is put into the project's coordinate space - and how a position there goes back.

The project has one coordinate space (project.json "screen"): states, buttons, regions and the model all live in it,
so one script works on any source. Each source chooses how its picture fits (per-source setting "fit"):
  stretch   scale both ways to the project's size (a different shape gets distorted)
  contain   keep the shape, scale to fit inside, black bars fill the rest (nothing lost, nothing distorted)
  cover     keep the shape, scale to fill, cut what sticks out (no bars, the edges are lost)
A tap at (x, y) in the project's space maps back to the source's own pixels with the same numbers (to_native), so
taps land where they were seen whatever the source's size."""
import numpy as np
from PIL import Image
from i18n import N_

MODES = {"stretch": N_("拉伸填滿(形狀不同會變形)"), "contain": N_("等比例,補黑邊(不變形,建議)"), "cover": N_("等比例填滿,裁掉多的部分")}


class Fit:
    """The transform of one picture size into the project's size: project = native * scale + offset."""

    def __init__(self, native, project, mode="stretch"):
        nw, nh = native
        pw, ph = project
        self.native, self.project, self.mode = (nw, nh), (pw, ph), mode if mode in MODES else "stretch"
        if self.mode == "stretch":
            self.sx, self.sy = pw / nw, ph / nh
            self.ox = self.oy = 0.0
        else:
            s = min(pw / nw, ph / nh) if self.mode == "contain" else max(pw / nw, ph / nh)
            self.sx = self.sy = s
            self.ox, self.oy = (pw - nw * s) / 2, (ph - nh * s) / 2

    def image(self, img):
        """An RGB array of the native size -> one of the project's size."""
        pw, ph = self.project
        nw, nh = self.native
        if self.mode == "stretch" or (self.sx, self.sy) == (pw / nw, ph / nh) and not (self.ox or self.oy):
            if (nw, nh) == (pw, ph):
                return np.ascontiguousarray(img)
            return np.asarray(Image.fromarray(img).resize((pw, ph), Image.BICUBIC))
        w, h = max(1, round(nw * self.sx)), max(1, round(nh * self.sy))
        scaled = Image.fromarray(img).resize((w, h), Image.BICUBIC)
        canvas = Image.new("RGB", (pw, ph))
        canvas.paste(scaled, (round(self.ox), round(self.oy)))      # cover: a negative offset cuts the edges
        return np.asarray(canvas)

    def to_native(self, x, y):
        """A position in the project's space -> the source's own pixels (clamped to its picture)."""
        nx, ny = (x - self.ox) / self.sx, (y - self.oy) / self.sy
        return min(max(nx, 0), self.native[0] - 1), min(max(ny, 0), self.native[1] - 1)

    def inside(self, x, y):
        """Is a project position on the picture (not on a black bar)?"""
        nx, ny = (x - self.ox) / self.sx, (y - self.oy) / self.sy
        return 0 <= nx < self.native[0] and 0 <= ny < self.native[1]


def project_size():
    import project
    return tuple(project.screen())
