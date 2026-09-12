"""
Crosshair Overlay — customizable, multi-monitor, 10 presets.

Hotkeys (the modifier defaults to Ctrl+Alt, change it in the Shortcuts tab):
  Mod+S       → Open / close the settings window
  Mod+H       → Hide / show the crosshair
  Mod+1 to 0  → Switch preset (1-10, 0 = preset 10)
  Mod+Q       → Quit
"""

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import colorchooser
import ctypes
import ctypes.wintypes as wt
import pystray
from PIL import Image, ImageDraw, ImageTk

# ─── Paths (relative to the script / exe) ────────────────────────────────────
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# ─── Win32 ───────────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WM_HOTKEY = 0x0312
WM_USER_REREGISTER = 0x0400 + 1

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

MODIFIER_CHOICES = {
    "Ctrl+Alt":       MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
    "Ctrl+Shift":     MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
    "Alt+Shift":      MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
    "Ctrl+Alt+Shift": MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
}

# ─── GUI theme ───────────────────────────────────────────────────────────────
# Gunsmith's bench: the interface is a neutral tool, and the orange marks only
# what is active or adjustable. The crosshair's color comes from the preset.
BG = "#23262A"
BG2 = "#2E3238"
BG3 = "#383D44"
FG = "#D8DCE1"
FG2 = "#8A9199"
ACCENT = "#E07A2F"
FONT = ("Bahnschrift", 10)
FONT_B = ("Bahnschrift", 10, "bold")
FONT_S = ("Bahnschrift", 9)
FONT_MONO = ("Consolas", 10)

# ─── Monitors ────────────────────────────────────────────────────────────────

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
        ("szDevice", wt.WCHAR * 32),
    ]


def get_monitors():
    monitors = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wt.BOOL, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM
    )

    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        rc = info.rcMonitor
        monitors.append({
            "name": info.szDevice.strip("\x00"),
            "x": rc.left, "y": rc.top,
            "w": rc.right - rc.left, "h": rc.bottom - rc.top,
            "primary": bool(info.dwFlags & 1),
        })
        return True

    cb_ref = MONITORENUMPROC(callback)
    user32.EnumDisplayMonitors(None, None, cb_ref, 0)
    monitors.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    return monitors


# ─── Config ──────────────────────────────────────────────────────────────────

DEFAULT_PRESETS = [
    {"name": "Preset 1",   "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#00FF00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Preset 2",   "show_cross": False, "show_circle": False, "show_dot": True,
     "color": "#00FF00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 5},
    {"name": "Preset 3",  "show_cross": True,  "show_circle": True,  "show_dot": True,
     "color": "#00FF00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Preset 4",   "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#FF0000", "outline": "#000000", "size": 18, "thickness": 2, "gap": 5, "dot_radius": 2},
    {"name": "Preset 5",    "show_cross": True,  "show_circle": True,  "show_dot": True,
     "color": "#00FFFF", "outline": "#000000", "size": 22, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Preset 6",   "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#FFFF00", "outline": "#222222", "size": 16, "thickness": 3, "gap": 3, "dot_radius": 1},
    {"name": "Preset 7",   "show_cross": True,  "show_circle": False, "show_dot": False,
     "color": "#FFFFFF", "outline": "#000000", "size": 24, "thickness": 1, "gap": 6, "dot_radius": 2},
    {"name": "Preset 8",    "show_cross": False, "show_circle": True,  "show_dot": True,
     "color": "#FF69B4", "outline": "#000000", "size": 15, "thickness": 2, "gap": 4, "dot_radius": 3},
    {"name": "Preset 9",  "show_cross": True,  "show_circle": True,  "show_dot": True,
     "color": "#FF8C00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Preset 10",    "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#4488FF", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
]


# The overlay's transparency color. A crosshair painted in it is invisible there
# while showing up normally in the preview, so no input may be allowed to set it.
CHROMA_KEY = "#FF00FE"
CHROMA_WARNING = ("%s is the transparency color: the crosshair would be invisible" % CHROMA_KEY)

_DIGITS = "0123456789"
_HEXDIGITS = "0123456789abcdefABCDEF"

SLIDER_RANGES = {
    "size": (5, 60),
    "thickness": (1, 8),
    "gap": (0, 20),
    "dot_radius": (1, 10),
}


def valid_color(value):
    """True if `value` is a usable #RRGGBB, chroma key excluded."""
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(c in _HEXDIGITS for c in value[1:])
            and value.upper() != CHROMA_KEY)


def _migrate_preset(p, defaults):
    """Migrate `shape`, backfill missing keys, clamp the numeric values.

    Unlike `code_to_preset()`, which rejects an out-of-range value, we clamp
    here: `config.json` is a local file, and a wild number typed by hand must
    not stop the app from starting.
    """
    if "shape" in p:
        # `shape` named ONE shape: "dot" must not also light up the cross.
        shape = p.pop("shape")
        p.setdefault("show_circle", shape == "circle")
        p.setdefault("show_dot", shape == "dot")
        p.setdefault("show_cross", shape not in ("none", "circle", "dot"))
    for key, value in defaults.items():
        p.setdefault(key, value)
    for key, (low, high) in SLIDER_RANGES.items():
        value = p.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            p[key] = defaults[key]
        else:
            p[key] = max(low, min(value, high))
    # a color Tk cannot parse would kill a .pyw with no window and no message
    for key in ("color", "outline"):
        if not valid_color(p.get(key)):
            p[key] = defaults[key]
    if not isinstance(p.get("name"), str):
        p["name"] = defaults["name"]
    for key in ("show_cross", "show_circle", "show_dot"):
        p[key] = bool(p.get(key))
    return p


def _clamp_index(value, high=None):
    """Integer index clamped to [0, high], falling back to 0 if it is not one."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value if high is None else max(0, min(value, high))


def load_config(monitor_count=None):
    """Always returns a usable config: keys guaranteed, indices clamped.

    `presets` and `preset` are normalized here once and for all, so consumers
    index them without guards. `monitor` is only capped when `monitor_count` is
    given: the caller alone knows how many screens exist.
    """
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                cfg = loaded
        except Exception:
            pass

    raw = cfg.get("presets")
    if not isinstance(raw, list):
        raw = []
    cfg["presets"] = [
        _migrate_preset(
            raw[i] if i < len(raw) and isinstance(raw[i], dict) else defaults.copy(),
            defaults,
        )
        for i, defaults in enumerate(DEFAULT_PRESETS)
    ]

    cfg["preset"] = _clamp_index(cfg.get("preset"), len(cfg["presets"]) - 1)
    cfg["monitor"] = _clamp_index(
        cfg.get("monitor"), None if monitor_count is None else monitor_count - 1
    )
    if not isinstance(cfg.get("modifier"), str) or cfg["modifier"] not in MODIFIER_CHOICES:
        cfg["modifier"] = "Ctrl+Alt"
    # leftover from per-game profiles: drop it rather than carry it forward on
    # every save, otherwise it survives indefinitely in existing files.
    cfg.pop("profiles", None)
    return cfg


def save_config(cfg):
    """Writes through a temporary file, then replaces.

    Writing straight into CONFIG_FILE truncates it before serializing: a preset
    name the UTF-8 encoder refuses would then leave a mangled file in place of
    all ten presets.
    """
    tmp = CONFIG_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ─── Shareable crosshair codes ───────────────────────────────────────────────
#
# Positional format, short and readable:
#     VSR1-<flags>-<fill>-<outline>-<size>-<thickness>-<gap>-<dot>
#     VSR1-5-FFFFFF-690F96-13-1-3-1
# flags: bit 0 cross, bit 1 circle, bit 2 dot.
#
# A code arrives from someone else (Discord, a forum), which makes it the only
# untrusted input in the app. Everything validates before a preset is touched,
# and an out-of-range code is rejected rather than quietly corrected.

CODE_PREFIX = "VSR1"
CODE_MAX_LEN = 64
CODE_FIELDS = ("size", "thickness", "gap", "dot_radius")
_FLAG_VALUES = frozenset(str(i) for i in range(8))


def preset_to_code(p):
    flags = ((1 if p.get("show_cross") else 0)
             | (2 if p.get("show_circle") else 0)
             | (4 if p.get("show_dot") else 0))
    parts = [CODE_PREFIX, str(flags),
             str(p["color"]).lstrip("#").upper(),
             str(p["outline"]).lstrip("#").upper()]
    parts += [str(int(p[k])) for k in CODE_FIELDS]
    return "-".join(parts)


def _parse_hex6(text):
    if len(text) != 6 or not all(c in _HEXDIGITS for c in text):
        raise ValueError("invalid color: %s" % text[:12])
    color = "#" + text.upper()
    if color == CHROMA_KEY:
        raise ValueError(CHROMA_WARNING)
    return color


def _parse_int(text, key):
    # no sign, no space, no exotic Unicode digit: int() would accept all three.
    if not text or not all(c in _DIGITS for c in text):
        raise ValueError("invalid number: %s" % text[:12])
    value = int(text)
    low, high = SLIDER_RANGES[key]
    if not low <= value <= high:
        raise ValueError("%s out of range (%d-%d): %d" % (key, low, high, value))
    return value


def code_to_preset(code):
    """Returns a preset's fields, or raises ValueError. Carries no name."""
    if not isinstance(code, str):
        raise ValueError("no code")
    code = code.strip()
    if not code:
        raise ValueError("empty code")
    if len(code) > CODE_MAX_LEN:
        raise ValueError("code too long")
    parts = code.split("-")
    if len(parts) != 4 + len(CODE_FIELDS):
        raise ValueError("wrong number of fields")
    if parts[0].upper() != CODE_PREFIX:
        raise ValueError("expected prefix %s" % CODE_PREFIX)

    if parts[1] not in _FLAG_VALUES:
        raise ValueError("invalid shape flags")
    flags = int(parts[1])

    values = {"color": _parse_hex6(parts[2]), "outline": _parse_hex6(parts[3])}
    for key, raw in zip(CODE_FIELDS, parts[4:]):
        values[key] = _parse_int(raw, key)

    values["show_cross"] = bool(flags & 1)
    values["show_circle"] = bool(flags & 2)
    values["show_dot"] = bool(flags & 4)
    return values



# ─── Tray icon image ────────────────────────────────────────────────────────

def create_tray_icon_image(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    mid = size // 2
    c = (0, 204, 102, 255)
    t = max(2, size // 16)
    draw.rectangle([4, mid - t // 2, size - 4, mid + t // 2], fill=c)
    draw.rectangle([mid - t // 2, 4, mid + t // 2, size - 4], fill=c)
    r = max(2, size // 10)
    draw.ellipse([mid - r, mid - r, mid + r, mid + r], fill=c)
    return img


# ─── Global Hotkeys (Win32 RegisterHotKey) ───────────────────────────────────

HOTKEY_QUIT = 1
HOTKEY_TOGGLE = 2
HOTKEY_SETTINGS = 3

HOTKEY_DEFS = {
    HOTKEY_QUIT:    0x51,  # Q
    HOTKEY_TOGGLE:  0x48,  # H
    HOTKEY_SETTINGS: 0x53, # S
}
for _i in range(1, 10):
    HOTKEY_DEFS[10 + _i] = 0x30 + _i  # 1-9
HOTKEY_DEFS[20] = 0x30  # 0 → preset 10

# Rows of the Shortcuts tab: the ids covered, the label, and the keys when several
# ids are grouped. For a single-id row the key is derived from HOTKEY_DEFS, which
# is what Windows actually registers — retyping it here would let the display lie
# if the virtual key ever changed.
HOTKEY_ROWS = (
    ((HOTKEY_SETTINGS,), "Settings", None),
    ((HOTKEY_TOGGLE,), "Hide / show", None),
    (tuple(range(11, 21)), "Preset 1-10", "1 … 0"),
    ((HOTKEY_QUIT,), "Quit", None),
)


class HotkeyManager:
    def __init__(self, root, callbacks, modifier_flags):
        self.root = root
        self.callbacks = callbacks
        self._mod = modifier_flags
        self.refused = []
        self._thread_id = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def _register_all(self):
        """Re-registers every hotkey and records the ones Windows refuses.

        `RegisterHotKey` fails when another application already holds the
        combination. Without this record the user would believe the shortcut is
        live. `refused` is replaced wholesale, never mutated in place, so the tk
        thread can read it without a lock.
        """
        for hk_id in HOTKEY_DEFS:
            user32.UnregisterHotKey(None, hk_id)
        refused = [hk_id for hk_id, vk in HOTKEY_DEFS.items()
                   if not user32.RegisterHotKey(None, hk_id, self._mod, vk)]
        self.refused = refused

    def _run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register_all()
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_USER_REREGISTER:
                self._register_all()
            elif msg.message == WM_HOTKEY:
                cb = self.callbacks.get(int(msg.wParam))
                if cb:
                    self.root.after(0, cb)

    def change_modifier(self, modifier_flags):
        """Asks the thread that owns the hotkeys to re-register them.

        `RegisterHotKey` binds hotkeys to the calling thread: re-registering
        from here would attach them to the wrong one and `WM_HOTKEY` would never
        arrive again.
        """
        self._mod = modifier_flags
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_USER_REREGISTER, 0, 0)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)


# ─── Overlay ─────────────────────────────────────────────────────────────────

class Overlay:
    def __init__(self, root, config, monitors):
        self.root = root
        self.config = config
        self.monitors = monitors
        self.visible = True
        self.TC = CHROMA_KEY

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title("ViseurOverlay")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", self.TC)
        self.win.config(bg=self.TC)

        self.canvas = tk.Canvas(self.win, bg=self.TC, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.apply()
        self.win.deiconify()
        self.win.after(500, self._make_click_through)
        self._keep_on_top()

    def apply(self):
        p = self.config["presets"][self.config["preset"]]
        mon_idx = _clamp_index(self.config["monitor"], len(self.monitors) - 1)
        mon = self.monitors[mon_idx]

        s = p["size"]
        extra = 10 if p["show_circle"] else 0
        ws = (s + extra) * 2 + 30
        self.ws = ws

        cx = mon["x"] + mon["w"] // 2 - ws // 2
        cy = mon["y"] + mon["h"] // 2 - ws // 2

        self.win.geometry(f"{ws}x{ws}+{cx}+{cy}")
        self.canvas.config(width=ws, height=ws)
        self._draw_crosshair(self.canvas, ws // 2, ws // 2, p)

    def _draw_crosshair(self, canvas, cx, cy, p):
        # Which setting serves which shape is also described in
        # SettingsWindow.SLIDER_SPECS, which uses it for graying: touching one
        # without the other leaves a live setting that does nothing, or the reverse.
        canvas.delete("all")
        color = p["color"]
        outline = p["outline"]
        s = p["size"]
        g = p["gap"]
        t = p["thickness"]
        ot = t + 2
        dr = p["dot_radius"]

        if p["show_circle"]:
            for c_, w_ in [(outline, ot), (color, t)]:
                canvas.create_oval(cx - s, cy - s, cx + s, cy + s, outline=c_, width=w_)

        if p.get("show_cross", True):
            ext = 5 if p["show_circle"] else 0
            for c_, w_ in [(outline, ot), (color, t)]:
                canvas.create_line(cx - s - ext, cy, cx - g, cy, fill=c_, width=w_)
                canvas.create_line(cx + g, cy, cx + s + ext, cy, fill=c_, width=w_)
                canvas.create_line(cx, cy - s - ext, cx, cy - g, fill=c_, width=w_)
                canvas.create_line(cx, cy + g, cx, cy + s + ext, fill=c_, width=w_)

        if p["show_dot"]:
            canvas.create_oval(cx-dr-1, cy-dr-1, cx+dr+1, cy+dr+1, fill=outline, outline=outline)
            canvas.create_oval(cx-dr, cy-dr, cx+dr, cy+dr, fill=color, outline=color)

    def _make_click_through(self):
        hwnd = user32.GetParent(self.win.winfo_id())
        if not hwnd:
            hwnd = self.win.winfo_id()
        self.hwnd = hwnd
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT)

    def _keep_on_top(self):
        if self.visible:
            self.win.attributes("-topmost", True)
        self.root.after(2000, self._keep_on_top)

    def toggle(self):
        if self.visible:
            self.win.withdraw()
        else:
            self.win.deiconify()
            self.win.after(200, self._make_click_through)
        self.visible = not self.visible


# ─── Settings GUI ────────────────────────────────────────────────────────────

class SettingsWindow:
    """Two tabs: the crosshair on one page, and the hotkey modifier."""

    # Key, label, and the shapes that use this setting. The third column must stay
    # in agreement with Overlay._draw_crosshair(): a setting no ticked shape uses
    # is grayed out, otherwise you can move it and see nothing happen. The order
    # is the one of the 2x2 grid, not the one of the VSR1 code.
    SLIDER_SPECS = (
        ("size", "Size", ("cross", "circle")),
        ("gap", "Gap", ("cross",)),
        ("thickness", "Thickness", ("cross", "circle")),
        ("dot_radius", "Dot size", ("dot",)),
    )

    def __init__(self, root, config, monitors, overlay):
        self.root = root
        self.config = config
        self.monitors = monitors
        self.overlay = overlay
        self.hotkeys = None
        self.win = None
        self.active_tab = "crosshair"
        self.editing = config["preset"]

    def toggle(self):
        if self.win and self.win.winfo_exists():
            self.win.destroy()
            self.win = None
            return
        # the preset may have changed since it was last opened (hotkey, tray)
        self.editing = _clamp_index(self.config["preset"], len(self.config["presets"]) - 1)
        self._build()

    # ── Building ─────────────────────────────────────────────────────────────

    def _build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Viseur — Settings")
        # No fixed geometry: the height the content needs scales with DPI (682 px
        # at 100%, 787 at 125%, 864 at 150%), and a hard-coded size would push the
        # Save button off the window. Let Tk size it, and allow vertical resizing
        # as a fallback.
        self.win.resizable(False, True)
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self._icon_photo = ImageTk.PhotoImage(create_tray_icon_image(32))
        self.win.iconphoto(False, self._icon_photo)
        self.win.protocol("WM_DELETE_WINDOW",
                          lambda: (self.win.destroy(), setattr(self, "win", None)))

        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", padx=15, pady=(12, 6))
        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True)

        self.tab_btns, self.tabs = {}, {}
        for key, label in (("crosshair", "Crosshair"), ("shortcuts", "Shortcuts")):
            btn = tk.Button(bar, text=label, command=lambda k=key: self._show_tab(k),
                            bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                            relief="flat", bd=0, font=FONT, padx=18, pady=4,
                            cursor="hand2")
            btn.pack(side="left", padx=(0, 3))
            self.tab_btns[key] = btn
            self.tabs[key] = tk.Frame(body, bg=BG)

        crosshair = self.tabs["crosshair"]
        self._build_screen(crosshair)
        self._build_presets(crosshair)
        self._build_name(crosshair)
        self._build_settings(crosshair)
        self._build_preview(crosshair)
        self._build_code(crosshair)
        self._build_shortcuts(self.tabs["shortcuts"])
        self._build_actions()

        self._load_preset(self.editing)
        self._show_tab(self.active_tab)
        # these run after mapping: call them earlier and Windows overwrites the
        # position when it shows the window, landing it on the primary screen.
        self.win.after(0, self._lock_height)
        self.win.after(0, self._place_on_monitor)
        self.win.lift()
        self.win.focus_force()

    def _show_tab(self, key):
        self.active_tab = key
        for name, frame in self.tabs.items():
            if name == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for name, btn in self.tab_btns.items():
            active = name == key
            btn.config(bg=ACCENT if active else BG3, fg="#1A1207" if active else FG)

    def _lock_height(self):
        """Pins the height to the taller of the two tabs.

        Without it the window, which has no fixed geometry, resizes on every
        switch. The measurement stays dynamic — hence correct at every DPI
        scale — unlike a hard-coded size, which pushed Save off-screen. An unmapped
        frame already reports its requested size, so there is no need to switch
        tabs to measure: doing so would flicker and would override the tab the
        user may have just picked. Width is pinned the same way, the window
        being unable to grow wider.
        """
        self.win.update_idletasks()
        current = self.tabs[self.active_tab]
        # what belongs to no tab: the tab bar and the action bar
        chrome_h = self.win.winfo_reqheight() - current.winfo_reqheight()
        chrome_w = self.win.winfo_reqwidth() - current.winfo_reqwidth()
        tallest = max(f.winfo_reqheight() for f in self.tabs.values())
        widest = max(f.winfo_reqwidth() for f in self.tabs.values())
        self.win.geometry("%dx%d" % (max(self.win.winfo_reqwidth(), chrome_w + widest),
                                     chrome_h + tallest))

    def _build_shortcuts(self, tab):
        f = self._section(tab, "Modifier", 12)
        self.modifier_var = tk.StringVar(value=self.config.get("modifier", "Ctrl+Alt"))
        om = tk.OptionMenu(f, self.modifier_var, *MODIFIER_CHOICES.keys(),
                           command=self._change_modifier)
        om.config(bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                  highlightthickness=0, font=FONT_S, relief="flat")
        om["menu"].config(bg=BG3, fg=FG, activebackground=ACCENT, font=FONT_S)
        om.pack(fill="x")

        tk.Label(tab, text="Applies to every shortcut below. Change it when one of them "
                           "clashes with a game.",
                 bg=BG, fg=FG2, font=FONT_S, justify="left", wraplength=440,
                 anchor="w").pack(fill="x", padx=15, pady=(5, 0))

        self.shortcut_rows = self._section(tab, "Keys")
        self._refresh_shortcuts()

    def _refresh_shortcuts(self):
        # Defensive guard. Tk does cancel the `after` calls of a destroyed widget
        # (measured), so the deferred refresh should never land after a close; we
        # simply don't want the absence of a silent TclError to depend on that
        # implementation detail.
        if not (self.win and self.win.winfo_exists()):
            return
        for child in self.shortcut_rows.winfo_children():
            child.destroy()
        modifier = self.modifier_var.get()
        refused = set(self.hotkeys.refused) if self.hotkeys else set()
        for ids, label, keys in HOTKEY_ROWS:
            keys = keys or chr(HOTKEY_DEFS[ids[0]])
            taken = any(i in refused for i in ids)
            row = tk.Frame(self.shortcut_rows, bg=BG2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=BG2, fg=FG, font=FONT,
                     anchor="w", padx=8, pady=4).pack(side="left")
            tk.Label(row, text="%s + %s" % (modifier, keys), bg=BG2,
                     fg=FG2 if taken else ACCENT, font=FONT_MONO,
                     anchor="e", padx=8).pack(side="right")
            if taken:
                tk.Label(row, text="taken by another app", bg=BG2, fg=FG2,
                         font=FONT_S, anchor="e").pack(side="right")

    def _change_modifier(self, choice):
        if choice not in MODIFIER_CHOICES:
            return
        # in memory straight away: without this, reopening the window would reload
        # the old value from config and a later Save would undo a change that is
        # already active.
        self.config["modifier"] = choice
        if self.hotkeys:
            self.hotkeys.change_modifier(MODIFIER_CHOICES[choice])
            # re-registration happens on the hotkey thread: give it time to record
            # the refusals before redrawing the list.
            self.win.after(250, self._refresh_shortcuts)
        else:
            self._refresh_shortcuts()
        self._set_status("Shortcuts now use %s — Save to keep it" % choice)

    def _place_on_monitor(self):
        """Centers the window on the chosen screen, anchored top if it overflows.

        At a high scale the content can exceed the screen height (864 px at
        150%). Windows would then centre the window and clip both top and
        bottom; anchoring it keeps at least the start visible, and the window
        stays vertically resizable. There is no scrolling: that is a known
        limit, not an oversight.
        """
        self.win.update_idletasks()
        mon = self.monitors[_clamp_index(self.config["monitor"], len(self.monitors) - 1)]
        need_w, need_h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = mon["x"] + max(10, (mon["w"] - need_w) // 2)
        y = mon["y"] + max(10, (mon["h"] - need_h) // 2)
        self.win.geometry("+%d+%d" % (x, y))

    def _section(self, parent, text, pady_top=8, bg=BG, fill="x"):
        """A section title, then the already-packed frame that takes its content."""
        tk.Label(parent, text=text, bg=BG, fg=ACCENT, font=FONT_B,
                 anchor="w").pack(fill="x", padx=15, pady=(pady_top, 2))
        frame = tk.Frame(parent, bg=bg)
        frame.pack(fill=fill, padx=15)
        return frame

    def _build_screen(self, tab):
        f = self._section(tab, "Screen", 12)

        labels = []
        for i, m in enumerate(self.monitors):
            tag = " ★" if m["primary"] else ""
            labels.append(f"{i+1}: {m['name']} ({m['w']}×{m['h']}){tag}")
        self.monitor_var = tk.StringVar(
            value=labels[_clamp_index(self.config["monitor"], len(labels) - 1)])
        om = tk.OptionMenu(f, self.monitor_var, *labels)
        om.config(bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                  highlightthickness=0, font=FONT_S, relief="flat")
        om["menu"].config(bg=BG3, fg=FG, activebackground=ACCENT, font=FONT_S)
        om.pack(fill="x")

    def _build_presets(self, tab):
        pf = self._section(tab, "Presets")

        self.preset_btns = []
        for i in range(10):
            btn = tk.Button(
                pf, text=self._preset_label(i),
                # largeur fixe : un nom personnalise est plus large qu'un simple
                # chiffre, et la fenetre ne peut pas s'elargir apres coup, donc
                # sans cela le bouton renomme prend la place de ses voisins.
                width=9, height=2, command=lambda idx=i: self._select_preset(idx),
                bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                relief="flat", font=FONT_S, bd=0, cursor="hand2",
            )
            btn.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="ew")
            self.preset_btns.append(btn)
        for c in range(5):
            pf.columnconfigure(c, weight=1)
        self._highlight_preset()

    def _build_name(self, tab):
        f = self._section(tab, "Name")
        self.name_var = tk.StringVar()
        tk.Entry(f, textvariable=self.name_var, bg=BG3, fg=FG, insertbackground=FG,
                 font=FONT, relief="flat", bd=3).pack(fill="x")

    def _build_settings(self, tab):
        sf = self._section(tab, "Settings", bg=BG2)

        # Shapes: three switches on one row
        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=(9, 5))
        tk.Label(row, text="Shape", bg=BG2, fg=FG, font=FONT,
                 width=9, anchor="w").pack(side="left")
        self.shape_vars = {}
        for key, text in (("cross", "Cross"), ("circle", "Circle"), ("dot", "Dot")):
            var = tk.BooleanVar()
            self.shape_vars[key] = var
            tk.Checkbutton(row, text=text, variable=var, bg=BG2, fg=FG,
                           selectcolor=BG3, activebackground=BG2, activeforeground=FG,
                           font=FONT, command=self._on_shape_change,
                           cursor="hand2").pack(side="left", padx=(0, 12))

        # Settings: a 2x2 grid, half the height of four stacked rows
        grid = tk.Frame(sf, bg=BG2)
        grid.pack(fill="x", padx=10, pady=(0, 3))
        self.sliders = {}
        for index, (key, text, _owners) in enumerate(self.SLIDER_SPECS):
            lo, hi = SLIDER_RANGES[key]
            cell = tk.Frame(grid, bg=BG2)
            cell.grid(row=index // 2, column=index % 2, sticky="ew", pady=2,
                      padx=(0, 10) if index % 2 == 0 else (0, 0))
            name = tk.Label(cell, text=text, bg=BG2, fg=FG, font=FONT_S,
                            width=9, anchor="w")
            name.pack(side="left")
            value = tk.Label(cell, text="0", bg=BG2, fg=ACCENT, font=FONT_MONO,
                             width=3, anchor="e")
            value.pack(side="right")
            scale = tk.Scale(
                cell, from_=lo, to=hi, orient="horizontal", showvalue=False,
                bg=BG2, fg=FG, troughcolor=BG3, activebackground=ACCENT,
                highlightthickness=0, bd=0, length=110, sliderlength=14,
                command=lambda v, lbl=value: (lbl.config(text=str(int(float(v)))),
                                              self._update_preview()),
            )
            scale.pack(side="left", fill="x", expand=True, padx=(4, 4))
            self.sliders[key] = (scale, value, name)
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        # Colors: both on one row
        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=(4, 10))
        self.colors = {}
        for which, text in (("color", "Fill"), ("outline", "Outline")):
            tk.Label(row, text=text, bg=BG2, fg=FG, font=FONT,
                     width=9 if which == "color" else 8,
                     anchor="w").pack(side="left")
            swatch = tk.Canvas(row, width=28, height=18, bd=1, relief="solid",
                               cursor="hand2", highlightthickness=0)
            swatch.pack(side="left", padx=(0, 5))
            swatch.bind("<Button-1>", lambda e, w=which: self._pick_color(w))
            value = tk.Label(row, bg=BG2, fg=FG2, font=FONT_MONO)
            value.pack(side="left", padx=(0, 18))
            self.colors[which] = (swatch, value)

    def _build_preview(self, tab):
        f = self._section(tab, "Preview", fill="none")
        self.preview = tk.Canvas(f, width=120, height=120, bg="#111111",
                                 highlightthickness=1, highlightbackground=BG3)
        self.preview.pack()

    def _build_code(self, tab):
        f = self._section(tab, "Crosshair code")
        self.code_var = tk.StringVar()
        tk.Entry(f, textvariable=self.code_var, state="readonly",
                 readonlybackground=BG3, fg=FG, font=FONT_MONO,
                 relief="flat", bd=3).pack(fill="x", pady=(0, 5))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x")
        tk.Button(row, text="Copy", command=self._copy_code, bg=BG3, fg=FG,
                  activebackground=BG2, activeforeground=FG, font=FONT_S,
                  relief="flat", bd=0, padx=14, pady=2, cursor="hand2").pack(side="left")
        tk.Button(row, text="Paste", command=self._paste_code, bg=BG3, fg=FG,
                  activebackground=BG2, activeforeground=FG, font=FONT_S,
                  relief="flat", bd=0, padx=14, pady=2,
                  cursor="hand2").pack(side="left", padx=(5, 0))

    def _build_actions(self):
        f = tk.Frame(self.win, bg=BG)
        f.pack(fill="x", padx=15, pady=(14, 12))
        tk.Button(f, text="Save", command=self._save, bg=ACCENT, fg="#1A1207",
                  activebackground=ACCENT, activeforeground="#1A1207",
                  font=FONT_B, relief="flat", bd=0, padx=22, pady=4,
                  cursor="hand2").pack(side="left")
        self.status = tk.Label(f, text="", bg=BG, fg=FG2, font=FONT_S, anchor="e")
        self.status.pack(side="right", fill="x", expand=True, padx=(10, 0))

    # ── State ────────────────────────────────────────────────────────────────

    def _preset_label(self, idx):
        """Button caption: the hotkey digit, plus the name once it says something.

        A default name is just "Preset <n>", which repeats the digit above it, so
        it is left out. Rename a preset and the name appears.
        """
        name = self.config["presets"][idx]["name"]
        if name == DEFAULT_PRESETS[idx]["name"]:
            return str(idx + 1)
        return "%d\n%s" % (idx + 1, name[:10])

    def _highlight_preset(self):
        for i, btn in enumerate(self.preset_btns):
            active = i == self.editing
            btn.config(bg=ACCENT if active else BG3, fg="#1A1207" if active else FG)

    def _select_preset(self, idx):
        self.editing = idx
        self._highlight_preset()
        self._load_preset(idx)

    def _apply_values(self, values):
        """The single place settings are written into the widgets.

        Tk ignores `Scale.set()` on a disabled slider, so the state is forced to
        normal while writing and the graying applied afterwards. Writing
        anywhere else without that order loses the value silently, which is why
        everything goes through here. `values` need not carry `name`.
        """
        for key, var in self.shape_vars.items():
            var.set(values["show_%s" % key])
        for which in self.colors:
            self._set_color(which, values[which])
        for key, (scale, value, _name) in self.sliders.items():
            scale.config(state="normal")
            scale.set(values[key])
            value.config(text=str(values[key]))
        self._sync_enabled()

    def _load_preset(self, idx):
        p = self.config["presets"][idx]
        self.name_var.set(p["name"])
        self._apply_values(p)
        self.code_var.set(preset_to_code(p))
        self._update_preview()

    def _read_current(self):
        p = {"name": self.name_var.get()}
        for which, (_swatch, value) in self.colors.items():
            p[which] = value.cget("text")
        for key, var in self.shape_vars.items():
            p["show_%s" % key] = var.get()
        for key, (scale, _value, _name) in self.sliders.items():
            p[key] = int(scale.get())
        return p

    def _sync_enabled(self):
        """Grays out the settings no ticked shape uses."""
        for key, _text, owners in self.SLIDER_SPECS:
            used = any(self.shape_vars[o].get() for o in owners)
            scale, value, name = self.sliders[key]
            scale.config(state="normal" if used else "disabled",
                         troughcolor=BG3 if used else BG2)
            name.config(fg=FG if used else FG2)
            value.config(fg=ACCENT if used else FG2)

    def _on_shape_change(self, *_):
        # only the check buttons can change what is grayed out
        self._sync_enabled()
        self._update_preview()

    def _set_color(self, which, hex_color):
        swatch, value = self.colors[which]
        swatch.config(bg=hex_color)
        value.config(text=hex_color)

    def _pick_color(self, which):
        current = self.colors[which][1].cget("text")
        result = colorchooser.askcolor(color=current, title="Pick a color")
        if result and result[1]:
            if not valid_color(result[1]):
                self._set_status(CHROMA_WARNING)
                return
            self._set_color(which, result[1])
            self._update_preview()

    def _update_preview(self):
        p = self._read_current()
        self.overlay._draw_crosshair(self.preview, 60, 60, p)
        self.code_var.set(preset_to_code(p))

    # ── Actions ──────────────────────────────────────────────────────────────

    def _copy_code(self):
        code = preset_to_code(self._read_current())
        self.win.clipboard_clear()
        self.win.clipboard_append(code)
        self._set_status("Copied")

    def _paste_code(self):
        try:
            pasted = self.win.clipboard_get()
        except Exception:
            # Tk raises the same error for an empty clipboard and for non-text
            # content (an image, files): don't claim it is one or the other.
            self._set_status("No crosshair code on the clipboard")
            return
        try:
            values = code_to_preset(pasted)
        except ValueError as err:
            self._set_status("Code rejected: %s" % err)
            return
        self._apply_values(values)
        self._update_preview()
        self._set_status("Code applied to preset %d — Save to keep it" % (self.editing + 1))

    def _save(self):
        p = self._read_current()
        self.config["presets"][self.editing] = p
        self.config["preset"] = self.editing

        try:
            self.config["monitor"] = int(self.monitor_var.get().split(":")[0]) - 1
        except Exception:
            self.config["monitor"] = 0
        if self.modifier_var.get() in MODIFIER_CHOICES:
            self.config["modifier"] = self.modifier_var.get()

        self.overlay.apply()
        try:
            save_config(self.config)
        except (OSError, ValueError) as err:
            # read-only folder, USB stick pulled, a name that cannot be encoded: a
            # .pyw has no console, so without this message the failure is silent.
            self._set_status("Could not write config.json: %s" % err)
            return
        self.preset_btns[self.editing].config(text=self._preset_label(self.editing))
        self._set_status("Saved")

    def _set_status(self, text):
        if getattr(self, "status", None):
            self.status.config(text=text[:80])


# ─── System Tray ─────────────────────────────────────────────────────────────

class TrayIcon:
    def __init__(self, root, config, overlay, settings, shutdown_fn):
        self.root = root
        self.config = config
        self.overlay = overlay
        self.settings = settings
        self.shutdown_fn = shutdown_fn
        self.icon = None
        self._start()

    def _start(self):
        image = create_tray_icon_image()

        preset_items = []
        for i in range(10):
            preset_items.append(
                pystray.MenuItem(
                    f"{i+1}: {self.config['presets'][i]['name']}",
                    self._make_switch(i),
                )
            )

        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide", lambda: self.root.after(0, self.overlay.toggle)),
            pystray.MenuItem("Settings", lambda: self.root.after(0, self.settings.toggle)),
            pystray.MenuItem("Presets", pystray.Menu(*preset_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.root.after(0, self.shutdown_fn)),
        )
        self.icon = pystray.Icon("Viseur", image, "Viseur", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def _make_switch(self, idx):
        def switch():
            self.config["preset"] = idx
            self.root.after(0, self.overlay.apply)
        return switch

    def stop(self):
        if self.icon:
            self.icon.stop()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    monitors = get_monitors()
    if not monitors:
        monitors = [{"name": "Default", "x": 0, "y": 0,
                      "w": user32.GetSystemMetrics(0), "h": user32.GetSystemMetrics(1),
                      "primary": True}]

    config = load_config(len(monitors))

    root = tk.Tk()
    root.withdraw()

    overlay = Overlay(root, config, monitors)
    settings = SettingsWindow(root, config, monitors, overlay)

    tray = None
    hotkeys = None

    def shutdown():
        nonlocal tray, hotkeys
        if hotkeys:
            hotkeys.stop()
        if tray:
            tray.stop()
        root.destroy()
        sys.exit(0)

    def switch_preset(idx):
        config["preset"] = idx
        overlay.apply()

    callbacks = {
        HOTKEY_QUIT: shutdown,
        HOTKEY_TOGGLE: overlay.toggle,
        HOTKEY_SETTINGS: settings.toggle,
    }
    for i in range(1, 10):
        callbacks[10 + i] = lambda idx=i-1: switch_preset(idx)
    callbacks[20] = lambda: switch_preset(9)

    mod_flags = MODIFIER_CHOICES.get(config.get("modifier", "Ctrl+Alt"),
                                      MODIFIER_CHOICES["Ctrl+Alt"])
    hotkeys = HotkeyManager(root, callbacks, mod_flags)
    settings.hotkeys = hotkeys
    tray = TrayIcon(root, config, overlay, settings, shutdown)

    root.mainloop()


if __name__ == "__main__":
    main()
