"""Copying a window's picture from Windows (any program: an emulator, an NVR client, a browser ...).

A window is picked by what it looks like from outside - no program is special here:
  {"title": "<text>", "title_mode": "exact" | "contains", "class": "<window class>", "process": "<name.exe>",
   "child_class": "<class of the child window that holds the picture>" (e.g. an emulator's render area)}
Empty fields match anything. PrintWindow with full content (works for GPU-drawn windows, ~16 ms, costs the program
nothing); a minimized window cannot be copied (grab() -> None)."""
import ctypes
import ctypes.wintypes as W
import os

import numpy as np
from PIL import Image

_u = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
_g = ctypes.windll.gdi32 if hasattr(ctypes, "windll") else None
_k = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None
_ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM) if hasattr(ctypes, "WINFUNCTYPE") else None   # Windows only
PW_CLIENTONLY, PW_RENDERFULLCONTENT = 1, 2


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


def text(h):
    n = _u.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    _u.GetWindowTextW(h, b, n + 1)
    return b.value


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    _u.GetClassNameW(h, b, 128)
    return b.value


def process(h):
    pid = W.DWORD()
    _u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    hp = _k.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not hp:
        return "", pid.value
    try:
        b = ctypes.create_unicode_buffer(512)
        n = W.DWORD(512)
        if _k.QueryFullProcessImageNameW(hp, 0, b, ctypes.byref(n)):
            return os.path.basename(b.value), pid.value
        return "", pid.value
    finally:
        _k.CloseHandle(hp)


def _match(h, spec):
    t = spec.get("title") or ""
    if t:
        tx = text(h)
        if (spec.get("title_mode") or "exact") == "contains":
            if t.lower() not in tx.lower():
                return False
        elif tx != t:
            return False
    if spec.get("class") and cls(h) != spec["class"]:
        return False
    if spec.get("process") and process(h)[0].lower() != spec["process"].lower():
        return False
    return True


SYSTEM_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}


def _cloaked(h):
    """Hidden by Windows itself (a suspended Settings app, a window on another virtual desktop)."""
    try:
        v = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(v), ctypes.sizeof(v))      # DWMWA_CLOAKED
        return v.value != 0
    except Exception:
        return False


def real(h):
    """A window a person works with: visible, titled, not a tool window, not hidden by Windows, not the desktop."""
    if not (_u.IsWindowVisible(h) and text(h)) or cls(h) in SYSTEM_CLASSES or _cloaked(h):
        return False
    ex = _u.GetWindowLongW(h, -20)                         # GWL_EXSTYLE
    return not ex & 0x00000080 or ex & 0x00040000          # WS_EX_TOOLWINDOW (unless WS_EX_APPWINDOW)


def windows(spec=None):
    """Windows people work with that match -> [{"hwnd", "title", "class", "process", "pid", "size"}]."""
    if not _u:
        return []
    out = []

    def cb(h, _):
        if real(h) and (spec is None or _match(h, spec)):
            r = W.RECT()
            _u.GetClientRect(h, ctypes.byref(r))
            name, pid = process(h)
            out.append({"hwnd": h, "title": text(h), "class": cls(h), "process": name, "pid": pid, "size": (r.right, r.bottom)})
        return True
    _u.EnumWindows(_ENUM(cb), 0)
    return out


def find(spec):
    """(top-level window, the window holding the picture) or (None, None)."""
    if not _u:
        return None, None
    tops = [w["hwnd"] for w in windows(spec)] or []
    if not tops:                                           # an emulator's main window may be hidden from the list
        found = []

        def cb(h, _):
            if _match(h, spec):
                found.append(h)
            return True
        _u.EnumWindows(_ENUM(cb), 0)
        tops = found
    for top in tops:
        if not spec.get("child_class"):
            return top, top
        kids = []

        def kcb(k, _):
            if cls(k) == spec["child_class"]:
                kids.append(k)
            return True
        _u.EnumChildWindows(top, _ENUM(kcb), 0)
        if kids:
            return top, kids[0]
    return None, None


class WindowCapture:
    """grab() -> (RGB image at `size` (or its own size when None), native (w, h)) or None. region = [x, y, w, h] of the
    window's own picture to keep (None = all)."""

    def __init__(self, spec, size=None, region=None):
        self.spec, self.size, self.region = dict(spec), size, region
        self.top = self.render = None

    def _ok(self):
        return self.render and _u.IsWindow(self.render) and _u.IsWindow(self.top)

    def available(self):
        if not _u:
            return False
        if not self._ok():
            self.top, self.render = find(self.spec)
        return bool(self.render) and not _u.IsIconic(self.top)

    def grab(self):
        if not self.available():
            return None
        r = W.RECT()
        _u.GetClientRect(self.render, ctypes.byref(r))
        w, h = r.right, r.bottom
        if w < 64 or h < 36:
            return None
        hdc = _u.GetDC(self.render)
        mdc = _g.CreateCompatibleDC(hdc)
        bmp = _g.CreateCompatibleBitmap(hdc, w, h)
        old = _g.SelectObject(mdc, bmp)
        try:
            # the client area only: a top-level window would otherwise be drawn with its frame and title bar, shifted
            # against the client coordinates taps are sent in
            if not _u.PrintWindow(self.render, mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
                return None
            bi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(w * h * 4)
            if not _g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0):
                return None
        finally:
            _g.SelectObject(mdc, old)
            _g.DeleteObject(bmp)
            _g.DeleteDC(mdc)
            _u.ReleaseDC(self.render, hdc)
        img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, 2::-1]      # BGRA -> RGB
        if img.max() == 0:
            return None                                    # not drawn (e.g. being restored)
        if self.region:
            x, y, rw, rh = [int(v) for v in self.region]
            img = img[y:y + rh, x:x + rw]
            w, h = img.shape[1], img.shape[0]
        if self.size and (w, h) != tuple(self.size):
            img = np.asarray(Image.fromarray(img).resize(tuple(self.size), Image.BICUBIC))
        else:
            img = np.ascontiguousarray(img)
        return img, (w, h)
