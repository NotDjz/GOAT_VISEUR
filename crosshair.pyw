"""
Crosshair Overlay — customizable, multi-monitor, 10 presets.

Hotkeys (the modifier defaults to Ctrl+Alt, change it in config.json):
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

# ─── Thème GUI ───────────────────────────────────────────────────────────────
# Etabli d'armurier : l'interface est un outil neutre, l'orange ne marque que ce
# qui est actif ou modifiable. La couleur du viseur reste celle du preset.
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


# Couleur de transparence de l'overlay : un viseur peint dans cette teinte y est
# invisible, alors qu'il s'affiche normalement dans l'apercu. Aucune entree ne
# doit pouvoir l'imposer.
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
    """Vrai si `value` est un #RRGGBB utilisable, chroma key exclu."""
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(c in _HEXDIGITS for c in value[1:])
            and value.upper() != CHROMA_KEY)


def _migrate_preset(p, defaults):
    """Migre `shape`, rebouche les cles absentes, borne les valeurs numeriques.

    Contrairement a `code_to_preset()` qui rejette une valeur hors bornes, on
    borne ici : `config.json` est un fichier local, et un chiffre aberrant tape
    a la main ne doit pas empecher l'application de demarrer.
    """
    if "shape" in p:
        # `shape` designait UNE forme : « dot » ne doit pas aussi allumer la croix.
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
    # une couleur illisible par Tk ferait mourir un .pyw sans fenetre ni message
    for key in ("color", "outline"):
        if not valid_color(p.get(key)):
            p[key] = defaults[key]
    if not isinstance(p.get("name"), str):
        p["name"] = defaults["name"]
    for key in ("show_cross", "show_circle", "show_dot"):
        p[key] = bool(p.get(key))
    return p


def _clamp_index(value, high=None):
    """Indice entier borne a [0, high], avec repli sur 0 si la valeur n'en est pas un."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value if high is None else max(0, min(value, high))


def load_config(monitor_count=None):
    """Rend toujours un config exploitable : cles garanties, indices bornes.

    `presets` et `preset` sont normalises ici une fois pour toutes, donc les
    consommateurs les indexent sans garde. `monitor` n'est borne par le haut que
    si `monitor_count` est fourni : seul l'appelant connait le nombre d'ecrans.
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
    # vestige des profils par jeu : la retirer plutot que la recopier a chaque
    # sauvegarde, sinon elle survit indefiniment dans les fichiers existants.
    cfg.pop("profiles", None)
    return cfg


def save_config(cfg):
    """Ecrit par un fichier temporaire, puis remplace.

    Ecrire directement dans CONFIG_FILE le tronque avant la serialisation : un
    nom de preset que l'encodeur UTF-8 refuse laisserait alors un fichier
    mutile a la place des dix presets.
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


# ─── Codes de viseur partageables ────────────────────────────────────────────
#
# Format positionnel, court et lisible :
#     VSR1-<flags>-<couleur>-<contour>-<taille>-<epaisseur>-<ecart>-<point>
#     VSR1-5-FFFFFF-690F96-13-1-3-1
# flags : bit 0 croix, bit 1 cercle, bit 2 point.
#
# Un code arrive d'un tiers (Discord, forum) : c'est la seule entree non fiable
# de l'application. Tout est valide avant qu'un preset ne soit touche, et un
# code hors bornes est rejete plutot que corrige en silence.

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
    # ni signe, ni espace, ni chiffre Unicode exotique : int() les accepterait.
    if not text or not all(c in _DIGITS for c in text):
        raise ValueError("invalid number: %s" % text[:12])
    value = int(text)
    low, high = SLIDER_RANGES[key]
    if not low <= value <= high:
        raise ValueError("%s out of range (%d-%d): %d" % (key, low, high, value))
    return value


def code_to_preset(code):
    """Rend les champs d'un preset, ou leve ValueError. Ne porte pas le nom."""
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


class HotkeyManager:
    def __init__(self, root, callbacks, modifier_flags):
        self.root = root
        self.callbacks = callbacks
        self._mod = modifier_flags
        self._thread_id = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def _register_all(self):
        for hk_id in HOTKEY_DEFS:
            user32.UnregisterHotKey(None, hk_id)
        for hk_id, vk in HOTKEY_DEFS.items():
            user32.RegisterHotKey(None, hk_id, self._mod, vk)

    def _run(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register_all()
        self._ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                cb = self.callbacks.get(int(msg.wParam))
                if cb:
                    self.root.after(0, cb)

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
        # Quel reglage sert a quelle forme est aussi decrit dans
        # SettingsWindow.SLIDER_SPECS, qui s'en sert pour griser : toucher l'un
        # sans l'autre laisse un reglage actif qui ne fait rien, ou l'inverse.
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
    """Une seule page : ecran, presets, nom, reglages, apercu, code, Save."""

    # Cle, libelle, et formes qui utilisent ce reglage. La troisieme colonne doit
    # rester d'accord avec Overlay._draw_crosshair() : un reglage qu'aucune forme
    # cochee n'utilise est grise, sans quoi on peut le bouger sans rien voir.
    # L'ordre est celui de la grille 2x2, pas celui du code VSR1.
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
        self.win = None
        self.editing = config["preset"]

    def toggle(self):
        if self.win and self.win.winfo_exists():
            self.win.destroy()
            self.win = None
            return
        # le preset a pu changer depuis la derniere ouverture (raccourci, tray)
        self.editing = _clamp_index(self.config["preset"], len(self.config["presets"]) - 1)
        self._build()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Viseur — Settings")
        # Pas de geometry fixe : la hauteur requise par le contenu depend de la
        # mise a l'echelle DPI (682 px a 100 %, 787 a 125 %, 864 a 150 %), et une
        # taille en dur y ferait sortir le bouton Save de la fenetre. On laisse Tk
        # dimensionner, et on autorise l'ajustement vertical comme recours.
        self.win.resizable(False, True)
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self._icon_photo = ImageTk.PhotoImage(create_tray_icon_image(32))
        self.win.iconphoto(False, self._icon_photo)
        self.win.protocol("WM_DELETE_WINDOW",
                          lambda: (self.win.destroy(), setattr(self, "win", None)))

        self._build_screen()
        self._build_presets()
        self._build_name()
        self._build_settings()
        self._build_preview()
        self._build_code()
        self._build_actions()

        self._load_preset(self.editing)
        self.win.lift()
        self.win.focus_force()

    def _section(self, text, pady_top=8, bg=BG, fill="x"):
        """Titre de section, puis le cadre deja empaquete qui recevra son contenu."""
        tk.Label(self.win, text=text, bg=BG, fg=ACCENT, font=FONT_B,
                 anchor="w").pack(fill="x", padx=15, pady=(pady_top, 2))
        frame = tk.Frame(self.win, bg=bg)
        frame.pack(fill=fill, padx=15)
        return frame

    def _build_screen(self):
        f = self._section("Screen", 12)

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

    def _build_presets(self):
        pf = self._section("Presets")

        self.preset_btns = []
        for i in range(10):
            btn = tk.Button(
                pf, text=self._preset_label(i),
                height=2, command=lambda idx=i: self._select_preset(idx),
                bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                relief="flat", font=FONT_S, bd=0, cursor="hand2",
            )
            btn.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="ew")
            self.preset_btns.append(btn)
        for c in range(5):
            pf.columnconfigure(c, weight=1)
        self._highlight_preset()

    def _build_name(self):
        f = self._section("Name")
        self.name_var = tk.StringVar()
        tk.Entry(f, textvariable=self.name_var, bg=BG3, fg=FG, insertbackground=FG,
                 font=FONT, relief="flat", bd=3).pack(fill="x")

    def _build_settings(self):
        sf = self._section("Settings", bg=BG2)

        # Formes : trois interrupteurs sur une ligne
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

        # Reglages : grille 2x2, moitie moins haute que quatre lignes empilees
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

        # Couleurs : les deux sur une ligne
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

    def _build_preview(self):
        f = self._section("Preview", fill="none")
        self.preview = tk.Canvas(f, width=120, height=120, bg="#111111",
                                 highlightthickness=1, highlightbackground=BG3)
        self.preview.pack()

    def _build_code(self):
        f = self._section("Crosshair code")
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

    # ── Etat ─────────────────────────────────────────────────────────────────

    def _preset_label(self, idx):
        return "%d\n%s" % (idx + 1, self.config["presets"][idx]["name"][:7])

    def _highlight_preset(self):
        for i, btn in enumerate(self.preset_btns):
            active = i == self.editing
            btn.config(bg=ACCENT if active else BG3, fg="#1A1207" if active else FG)

    def _select_preset(self, idx):
        self.editing = idx
        self._highlight_preset()
        self._load_preset(idx)

    def _load_preset(self, idx):
        p = self.config["presets"][idx]
        self.name_var.set(p["name"])
        for key, var in self.shape_vars.items():
            var.set(p["show_%s" % key])
        for which in self.colors:
            self._set_color(which, p[which])
        # Tk ignore Scale.set() sur un curseur desactive : forcer l'etat actif
        # pendant l'ecriture, puis appliquer le grisage du nouveau preset. Sans
        # ce detour la valeur de l'ancien preset survit et Save la reecrit.
        for key, (scale, value, _name) in self.sliders.items():
            scale.config(state="normal")
            scale.set(p[key])
            value.config(text=str(p[key]))
        self._sync_enabled()
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
        """Grise les reglages qu'aucune forme cochee n'utilise."""
        for key, _text, owners in self.SLIDER_SPECS:
            used = any(self.shape_vars[o].get() for o in owners)
            scale, value, name = self.sliders[key]
            scale.config(state="normal" if used else "disabled",
                         troughcolor=BG3 if used else BG2)
            name.config(fg=FG if used else FG2)
            value.config(fg=ACCENT if used else FG2)

    def _on_shape_change(self, *_):
        # seules les cases a cocher peuvent changer ce qui est grise
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
            # Tk leve la meme erreur pour un presse-papiers vide et pour un
            # contenu non textuel (image, fichiers) : ne pas affirmer l'un des deux.
            self._set_status("No crosshair code on the clipboard")
            return
        try:
            values = code_to_preset(pasted)
        except ValueError as err:
            self._set_status("Code rejected: %s" % err)
            return
        for key, var in self.shape_vars.items():
            var.set(values["show_%s" % key])
        for which in self.colors:
            self._set_color(which, values[which])
        for key, (scale, _value, _name) in self.sliders.items():
            scale.config(state="normal")   # cf. _load_preset
            scale.set(values[key])
        self._sync_enabled()
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

        self.overlay.apply()
        try:
            save_config(self.config)
        except (OSError, ValueError) as err:
            # dossier en lecture seule, cle USB retiree, nom impossible a encoder :
            # le .pyw n'a pas de console, donc sans ce message l'echec serait muet.
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
    tray = TrayIcon(root, config, overlay, settings, shutdown)

    root.mainloop()


if __name__ == "__main__":
    main()
