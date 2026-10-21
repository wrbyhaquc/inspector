"""Mouse and keyboard for Windows programs (the hand of the window and screen-region sources).

Two ways, chosen per source:
  message  post the mouse / key messages straight to the window: works while it is behind other windows and never
           moves the real mouse - but some programs (many DirectX / full-screen views) ignore posted input
  mouse    move the real cursor and click (SendInput): works with anything visible, the window must be on top and
           nobody should be using the mouse meanwhile
Positions arrive in the window's (or the screen's) own pixels."""
import ctypes
import ctypes.wintypes as W
import time

_u = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
MK_LBUTTON = 0x0001
KEYS = {"esc": 0x1B, "back": 0x08, "enter": 0x0D, "tab": 0x09, "space": 0x20, "left": 0x25, "up": 0x26, "right": 0x27,
        "down": 0x28, "f5": 0x74}


def _lp(x, y):
    return (int(y) << 16) | (int(x) & 0xFFFF)


class _MI(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _KI(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _IU(ctypes.Union):
    _fields_ = [("mi", _MI), ("ki", _KI)]


class _IN(ctypes.Structure):
    _fields_ = [("type", W.DWORD), ("u", _IU)]


def _send(*inputs):
    arr = (_IN * len(inputs))(*inputs)
    _u.SendInput(len(inputs), arr, ctypes.sizeof(_IN))


def _mouse(flags):
    i = _IN()
    i.type = 0
    i.u.mi = _MI(0, 0, 0, flags, 0, None)
    return i


def _key(vk=0, scan=0, flags=0):
    i = _IN()
    i.type = 1
    i.u.ki = _KI(vk, scan, flags, 0, None)
    return i


def to_screen(hwnd, x, y):
    p = W.POINT(int(x), int(y))
    _u.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y


# ---- message: into the window, the real mouse stays where it is ----
def msg_press(hwnd, x, y, ms=60):
    _u.PostMessageW(hwnd, WM_MOUSEMOVE, 0, _lp(x, y))
    _u.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(x, y))
    time.sleep(ms / 1000)
    _u.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(x, y))


def msg_drag(hwnd, x1, y1, x2, y2, ms=400, steps=12):
    _u.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(x1, y1))
    for k in range(1, steps + 1):
        time.sleep(ms / 1000 / steps)
        _u.PostMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, _lp(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps))
    _u.PostMessageW(hwnd, WM_LBUTTONUP, 0, _lp(x2, y2))


def msg_key(hwnd, name):
    vk = KEYS.get(name, 0x1B)
    _u.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    _u.PostMessageW(hwnd, WM_KEYUP, vk, 0)


def msg_text(hwnd, text):
    for ch in text:
        _u.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)


# ---- mouse: the real cursor (screen pixels) ----
def mouse_press(sx, sy, ms=60):
    _u.SetCursorPos(int(sx), int(sy))
    _send(_mouse(0x0002))                                   # left down
    time.sleep(ms / 1000)
    _send(_mouse(0x0004))                                   # left up


def mouse_drag(sx1, sy1, sx2, sy2, ms=400, steps=15):
    _u.SetCursorPos(int(sx1), int(sy1))
    _send(_mouse(0x0002))
    for k in range(1, steps + 1):
        time.sleep(ms / 1000 / steps)
        _u.SetCursorPos(int(sx1 + (sx2 - sx1) * k / steps), int(sy1 + (sy2 - sy1) * k / steps))
    _send(_mouse(0x0004))


def key_press(name):
    vk = KEYS.get(name, 0x1B)
    _send(_key(vk), _key(vk, flags=0x0002))


def key_text(text):
    for ch in text:                                         # KEYEVENTF_UNICODE: any character
        _send(_key(0, ord(ch), 0x0004), _key(0, ord(ch), 0x0004 | 0x0002))


def bring_front(hwnd):
    try:
        if _u.IsIconic(hwnd):
            _u.ShowWindow(hwnd, 9)                          # SW_RESTORE
        _u.SetForegroundWindow(hwnd)
    except Exception:
        pass
