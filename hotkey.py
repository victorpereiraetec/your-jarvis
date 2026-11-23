"""Atalhos globais do Windows via RegisterHotKey — sem dependência externa.

Especificação: "ctrl+alt+j", "win+shift+s", "f9". A thread dona do registro é a
mesma que roda o GetMessage, requisito do Windows.
"""
import ctypes, ctypes.wintypes as w, sys, threading

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_NAMED = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "\\": 0xDC, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA, "'": 0xDE,
}
for _i in range(1, 13):
    _NAMED[f"f{_i}"] = 0x6F + _i  # VK_F1 = 0x70


def parse(spec):
    mods = MOD_NOREPEAT
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts:
        raise ValueError("atalho vazio")
    key = parts[-1]
    for p in parts[:-1]:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "super", "meta"):
            mods |= MOD_WIN
        else:
            raise ValueError(f"modificador desconhecido: {p}")
    if key in _NAMED:
        vk = _NAMED[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"tecla desconhecida: {key}")
    return mods, vk


class Hotkeys(threading.Thread):
    """bindings: [{"spec": "ctrl+alt+j", "cb": callable, "label": "..."}]"""

    def __init__(self, bindings):
        super().__init__(daemon=True, name="hotkeys")
        self.bindings = [b for b in bindings if b.get("spec")]
        self.status = {}

    def run(self):
        if sys.platform != "win32":
            return
        u = ctypes.windll.user32
        u.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
        u.RegisterHotKey.restype = w.BOOL
        u.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        u.GetMessageW.restype = ctypes.c_int
        for i, b in enumerate(self.bindings, start=1):
            try:
                mods, vk = parse(b["spec"])
                self.status[b["spec"]] = bool(u.RegisterHotKey(None, i, mods, vk))
            except Exception as e:
                self.status[b["spec"]] = False
                print(f"[hotkey] {b['spec']}: {e}")
        msg = w.MSG()
        while True:
            ret = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_HOTKEY and 1 <= int(msg.wParam) <= len(self.bindings):
                try:
                    self.bindings[int(msg.wParam) - 1]["cb"]()
                except Exception:
                    pass
