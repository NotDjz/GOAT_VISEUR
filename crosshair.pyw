"""
Crosshair Overlay — viseur personnalisable, multi-écran, 10 presets.

Raccourcis :
  Ctrl+Alt+S       → Ouvrir / fermer les paramètres
  Ctrl+Alt+H       → Masquer / afficher le viseur
  Ctrl+Alt+1 à 0   → Changer de preset (1-10, 0 = preset 10)
  Ctrl+Alt+Q       → Quitter
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

# ─── Chemins (relatifs au script / exe) ─────────────────────────────────────
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
MOD_CTRL_ALT = 0x0002 | 0x0001 | 0x4000

# ─── Thème GUI ───────────────────────────────────────────────────────────────
BG = "#1e1e1e"
BG2 = "#2d2d2d"
BG3 = "#3c3c3c"
FG = "#e0e0e0"
FG2 = "#999999"
ACCENT = "#00cc66"
FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_S = ("Segoe UI", 9)

# ─── Moniteurs ───────────────────────────────────────────────────────────────

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
    {"name": "Croix",   "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#00FF00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Point",   "show_cross": False, "show_circle": False, "show_dot": True,
     "color": "#00FF00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 5},
    {"name": "Cercle",  "show_cross": True,  "show_circle": True,  "show_dot": True,
     "color": "#00FF00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Rouge",   "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#FF0000", "outline": "#000000", "size": 18, "thickness": 2, "gap": 5, "dot_radius": 2},
    {"name": "Cyan",    "show_cross": True,  "show_circle": True,  "show_dot": True,
     "color": "#00FFFF", "outline": "#000000", "size": 22, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Jaune",   "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#FFFF00", "outline": "#222222", "size": 16, "thickness": 3, "gap": 3, "dot_radius": 1},
    {"name": "Blanc",   "show_cross": True,  "show_circle": False, "show_dot": False,
     "color": "#FFFFFF", "outline": "#000000", "size": 24, "thickness": 1, "gap": 6, "dot_radius": 2},
    {"name": "Rose",    "show_cross": False, "show_circle": True,  "show_dot": True,
     "color": "#FF69B4", "outline": "#000000", "size": 15, "thickness": 2, "gap": 4, "dot_radius": 3},
    {"name": "Orange",  "show_cross": True,  "show_circle": True,  "show_dot": True,
     "color": "#FF8C00", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
    {"name": "Bleu",    "show_cross": True,  "show_circle": False, "show_dot": True,
     "color": "#4488FF", "outline": "#000000", "size": 20, "thickness": 2, "gap": 4, "dot_radius": 2},
]


def _migrate_preset(p):
    if "shape" in p:
        p["show_cross"] = p.pop("shape") not in ("none",)
    p.setdefault("show_cross", True)
    return p


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for p in cfg.get("presets", []):
                _migrate_preset(p)
            while len(cfg.get("presets", [])) < 10:
                cfg["presets"].append(DEFAULT_PRESETS[len(cfg["presets"])].copy())
            return cfg
        except Exception:
            pass
    return {"monitor": 0, "preset": 0, "presets": [p.copy() for p in DEFAULT_PRESETS]}


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


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


class HotkeyManager:
    def __init__(self, root, callbacks):
        self.root = root
        self.callbacks = callbacks
        self._thread_id = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        for hk_id, vk in HOTKEY_DEFS.items():
            user32.RegisterHotKey(None, hk_id, MOD_CTRL_ALT, vk)
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                hk_id = msg.wParam
                cb = self.callbacks.get(hk_id)
                if cb:
                    self.root.after(0, cb)

    def stop(self):
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)


# ─── Overlay ─────────────────────────────────────────────────────────────────

class Overlay:
    def __init__(self, root, config, monitors):
        self.root = root
        self.config = config
        self.monitors = monitors
        self.visible = True
        self.TC = "#FF00FE"

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
        mon_idx = min(self.config["monitor"], len(self.monitors) - 1)
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
    def __init__(self, root, config, monitors, overlay):
        self.root = root
        self.config = config
        self.monitors = monitors
        self.overlay = overlay
        self.win = None
        self.editing = config["preset"]

    def toggle(self):
        if self.win and self.win.winfo_exists():
            self.win.destroy()
            self.win = None
            return
        self._build()

    def _build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Viseur — Paramètres")
        self.win.geometry("440x740")
        self.win.resizable(False, False)
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self._icon_photo = ImageTk.PhotoImage(create_tray_icon_image(32))
        self.win.iconphoto(False, self._icon_photo)
        self.win.protocol("WM_DELETE_WINDOW", lambda: (self.win.destroy(), setattr(self, "win", None)))

        # ── Écran ──
        self._section("Écran", 0)
        f = tk.Frame(self.win, bg=BG)
        f.pack(fill="x", padx=15, pady=(0, 8))

        labels = []
        for i, m in enumerate(self.monitors):
            tag = " ★" if m["primary"] else ""
            labels.append(f"{i+1}: {m['name']} ({m['w']}×{m['h']}){tag}")

        self.monitor_var = tk.StringVar(value=labels[min(self.config["monitor"], len(labels)-1)])
        om = tk.OptionMenu(f, self.monitor_var, *labels)
        om.config(bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                  highlightthickness=0, font=FONT_S, relief="flat")
        om["menu"].config(bg=BG3, fg=FG, activebackground=ACCENT, font=FONT_S)
        om.pack(fill="x")

        # ── Presets ──
        self._section("Presets", 0)
        pf = tk.Frame(self.win, bg=BG)
        pf.pack(fill="x", padx=15, pady=(0, 8))

        self.preset_btns = []
        for i in range(10):
            name = self.config["presets"][i]["name"]
            short = name[:6]
            btn = tk.Button(
                pf, text=f"{i+1}\n{short}", width=5, height=2,
                command=lambda idx=i: self._select_preset(idx),
                bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                relief="flat", font=("Segoe UI", 8), bd=0,
            )
            btn.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="ew")
            self.preset_btns.append(btn)
        for c in range(5):
            pf.columnconfigure(c, weight=1)

        self._highlight_preset()

        # ── Paramètres du preset ──
        self._section("Paramètres", 0)

        sf = tk.Frame(self.win, bg=BG2, bd=1, relief="flat")
        sf.pack(fill="x", padx=15, pady=(0, 8))

        # Nom
        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(row, text="Nom :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(row, textvariable=self.name_var, bg=BG3, fg=FG, insertbackground=FG,
                 font=FONT, relief="flat", bd=2).pack(side="left", fill="x", expand=True)

        # Croix / Cercle / Point
        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text="Forme :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
        self.cross_var = tk.BooleanVar()
        self.circle_var = tk.BooleanVar()
        self.dot_var = tk.BooleanVar()
        for text, var in [("Croix", self.cross_var), ("Cercle", self.circle_var), ("Point", self.dot_var)]:
            cb = tk.Checkbutton(row, text=text, variable=var, bg=BG2, fg=FG,
                                selectcolor=BG3, activebackground=BG2, activeforeground=FG,
                                font=FONT, command=self._on_change)
            cb.pack(side="left", padx=(0, 10))

        # Couleurs
        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text="Couleur :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
        self.color_swatch = tk.Canvas(row, width=30, height=20, bd=1, relief="solid", cursor="hand2")
        self.color_swatch.pack(side="left", padx=(0, 5))
        self.color_swatch.bind("<Button-1>", lambda e: self._pick_color("color"))
        self.color_label = tk.Label(row, bg=BG2, fg=FG2, font=FONT_S)
        self.color_label.pack(side="left")

        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text="Contour :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
        self.outline_swatch = tk.Canvas(row, width=30, height=20, bd=1, relief="solid", cursor="hand2")
        self.outline_swatch.pack(side="left", padx=(0, 5))
        self.outline_swatch.bind("<Button-1>", lambda e: self._pick_color("outline"))
        self.outline_label = tk.Label(row, bg=BG2, fg=FG2, font=FONT_S)
        self.outline_label.pack(side="left")

        # Sliders
        self.sliders = {}
        for label, key, lo, hi in [
            ("Taille", "size", 5, 60),
            ("Épaisseur", "thickness", 1, 8),
            ("Espace", "gap", 0, 20),
            ("Rayon point", "dot_radius", 1, 10),
        ]:
            row = tk.Frame(sf, bg=BG2)
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{label} :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
            val_label = tk.Label(row, text="0", bg=BG2, fg=ACCENT, font=FONT_B, width=3)
            val_label.pack(side="right")
            scale = tk.Scale(
                row, from_=lo, to=hi, orient="horizontal", showvalue=False,
                bg=BG2, fg=FG, troughcolor=BG3, activebackground=ACCENT,
                highlightthickness=0, bd=0, length=200,
                command=lambda v, lbl=val_label: (lbl.config(text=str(int(float(v)))), self._on_change()),
            )
            scale.pack(side="left", fill="x", expand=True, padx=(5, 5))
            self.sliders[key] = (scale, val_label)

        tk.Frame(sf, bg=BG2, height=8).pack()

        # ── Aperçu ──
        self._section("Aperçu", 0)
        pv_frame = tk.Frame(self.win, bg=BG)
        pv_frame.pack(pady=(0, 8))

        self.preview = tk.Canvas(pv_frame, width=120, height=120, bg="#111111",
                                 highlightthickness=1, highlightbackground=BG3)
        self.preview.pack()

        # ── Boutons ──
        bf = tk.Frame(self.win, bg=BG)
        bf.pack(fill="x", padx=15, pady=(0, 10))

        tk.Button(bf, text="Appliquer", command=self._apply, bg=ACCENT, fg="#000000",
                  font=FONT_B, relief="flat", padx=15, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(bf, text="Sauvegarder", command=self._save, bg=BG3, fg=FG,
                  font=FONT, relief="flat", padx=10, cursor="hand2").pack(side="left", padx=(0, 8))

        self._load_preset(self.editing)
        self.win.lift()
        self.win.focus_force()

    def _section(self, text, pady_top=5):
        tk.Label(self.win, text=text, bg=BG, fg=ACCENT, font=FONT_B,
                 anchor="w").pack(fill="x", padx=15, pady=(pady_top, 2))

    def _highlight_preset(self):
        for i, btn in enumerate(self.preset_btns):
            btn.config(bg=ACCENT if i == self.editing else BG3,
                       fg="#000000" if i == self.editing else FG)

    def _select_preset(self, idx):
        self.editing = idx
        self._highlight_preset()
        self._load_preset(idx)

    def _load_preset(self, idx):
        p = self.config["presets"][idx]
        self.name_var.set(p["name"])
        self.cross_var.set(p.get("show_cross", True))
        self.circle_var.set(p["show_circle"])
        self.dot_var.set(p["show_dot"])
        self.color_swatch.config(bg=p["color"])
        self.color_label.config(text=p["color"])
        self.outline_swatch.config(bg=p["outline"])
        self.outline_label.config(text=p["outline"])
        for key, (scale, val_label) in self.sliders.items():
            scale.set(p[key])
            val_label.config(text=str(p[key]))
        self._update_preview()

    def _read_current(self):
        return {
            "name": self.name_var.get(),
            "show_cross": self.cross_var.get(),
            "show_circle": self.circle_var.get(),
            "show_dot": self.dot_var.get(),
            "color": self.color_label.cget("text"),
            "outline": self.outline_label.cget("text"),
            "size": int(self.sliders["size"][0].get()),
            "thickness": int(self.sliders["thickness"][0].get()),
            "gap": int(self.sliders["gap"][0].get()),
            "dot_radius": int(self.sliders["dot_radius"][0].get()),
        }

    def _on_change(self, *_):
        self._update_preview()

    def _pick_color(self, which):
        current = self.color_label.cget("text") if which == "color" else self.outline_label.cget("text")
        result = colorchooser.askcolor(color=current, title="Choisir une couleur")
        if result and result[1]:
            hex_color = result[1]
            if which == "color":
                self.color_swatch.config(bg=hex_color)
                self.color_label.config(text=hex_color)
            else:
                self.outline_swatch.config(bg=hex_color)
                self.outline_label.config(text=hex_color)
            self._update_preview()

    def _update_preview(self):
        p = self._read_current()
        self.overlay._draw_crosshair(self.preview, 60, 60, p)

    def _apply(self):
        p = self._read_current()
        self.config["presets"][self.editing] = p
        self.config["preset"] = self.editing

        mon_str = self.monitor_var.get()
        try:
            self.config["monitor"] = int(mon_str.split(":")[0]) - 1
        except Exception:
            self.config["monitor"] = 0

        self.overlay.apply()
        self.preset_btns[self.editing].config(text=f"{self.editing+1}\n{p['name'][:6]}")

    def _save(self):
        self._apply()
        save_config(self.config)


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
            pystray.MenuItem("Afficher/Masquer", lambda: self.root.after(0, self.overlay.toggle)),
            pystray.MenuItem("Paramètres", lambda: self.root.after(0, self.settings.toggle)),
            pystray.MenuItem("Presets", pystray.Menu(*preset_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", lambda: self.root.after(0, self.shutdown_fn)),
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

    config = load_config()
    config["monitor"] = min(config["monitor"], len(monitors) - 1)

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

    hotkeys = HotkeyManager(root, callbacks)
    tray = TrayIcon(root, config, overlay, settings, shutdown)

    root.mainloop()


if __name__ == "__main__":
    main()
