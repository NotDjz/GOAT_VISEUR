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


# ─── Processus au premier plan ───────────────────────────────────────────────

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32 = ctypes.windll.kernel32


def foreground_exe():
    """Executable de la fenetre au premier plan, ou None.

    Rend None pour nos propres fenetres : sans cela, ouvrir les parametres
    ferait de Viseur lui-meme le « jeu au premier plan ».
    """
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value or pid.value == kernel32.GetCurrentProcessId():
            return None
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wt.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            name = buf.value.rsplit("\\", 1)[-1].lower()
            # un substitut UTF-16 non apparie ferait echouer l'ecriture de
            # config.json apres que open(..., "w") l'ait deja vide.
            name.encode("utf-8")
            return name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


# ─── Demarrage avec Windows (raccourci .lnk, sans registre) ──────────────────

CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
IID_ISHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
IID_IPERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_byte * 8)]


def _startup_path():
    """Chemin du raccourci de demarrage, ou None si APPDATA est introuvable."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup", "Viseur.lnk")


def _com_call(ptr, index, argtypes=(), *args):
    """Appelle la methode d'indice `index` dans la vtable de l'interface COM.

    Le pointeur n'est donne qu'une fois : le passer en premier argument de la
    methode est l'affaire de cette fonction, pas de l'appelant.
    """
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    return proto(vtable[index])(ptr, *args)


def _write_shortcut(path, target, workdir, arguments=None):
    """Ecrit un .lnk via IShellLink. Pas de subprocess, pas de dependance."""
    ole32 = ctypes.OleDLL("ole32")

    def guid(text):
        g = _GUID()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    ole32.CoInitialize(None)
    try:
        link = ctypes.c_void_p()
        ole32.CoCreateInstance(ctypes.byref(guid(CLSID_SHELL_LINK)), None, 1,
                               ctypes.byref(guid(IID_ISHELL_LINK_W)), ctypes.byref(link))
        try:
            _com_call(link, 20, (ctypes.c_wchar_p,), target)             # SetPath
            _com_call(link, 9, (ctypes.c_wchar_p,), workdir)             # SetWorkingDirectory
            if arguments:
                _com_call(link, 11, (ctypes.c_wchar_p,), arguments)      # SetArguments

            persist = ctypes.c_void_p()
            _com_call(link, 0, (ctypes.c_void_p, ctypes.c_void_p),
                      ctypes.byref(guid(IID_IPERSIST_FILE)), ctypes.byref(persist))
            try:
                _com_call(persist, 6, (ctypes.c_wchar_p, ctypes.c_int), path, True)
            finally:
                _com_call(persist, 2)                                     # Release
        finally:
            _com_call(link, 2)
    finally:
        ole32.CoUninitialize()


def startup_enabled():
    path = _startup_path()
    return bool(path) and os.path.exists(path)


def set_startup(enabled):
    """Cree ou supprime le raccourci de demarrage. Rend l'etat reellement obtenu."""
    path = _startup_path()
    if not path:
        return False
    try:
        if not enabled:
            if os.path.exists(path):
                os.remove(path)
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if getattr(sys, "frozen", False):
            _write_shortcut(path, sys.executable, SCRIPT_DIR)
        else:
            launcher = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(launcher):
                launcher = sys.executable
            _write_shortcut(path, launcher, SCRIPT_DIR,
                            '"%s"' % os.path.join(SCRIPT_DIR, "crosshair.pyw"))
        return os.path.exists(path)
    except Exception:
        return os.path.exists(path)



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

    `presets`, `preset` et `profiles` sont normalises ici une fois pour toutes,
    donc les consommateurs les indexent sans garde. `monitor` n'est borne par le
    haut que si `monitor_count` est fourni : seul l'appelant connait le nombre
    d'ecrans.
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

    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    cfg["profiles"] = {
        exe.strip().lower(): _clamp_index(idx, len(cfg["presets"]) - 1)
        for exe, idx in profiles.items()
        if isinstance(exe, str) and exe.strip()
    }
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


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
        raise ValueError("couleur invalide : %s" % text[:12])
    color = "#" + text.upper()
    if color == CHROMA_KEY:
        raise ValueError("%s est la couleur de transparence : le viseur serait invisible"
                         % CHROMA_KEY)
    return color


def _parse_int(text, key):
    # ni signe, ni espace, ni chiffre Unicode exotique : int() les accepterait.
    if not text or not all(c in _DIGITS for c in text):
        raise ValueError("nombre invalide : %s" % text[:12])
    value = int(text)
    low, high = SLIDER_RANGES[key]
    if not low <= value <= high:
        raise ValueError("%s hors bornes (%d-%d) : %d" % (key, low, high, value))
    return value


def code_to_preset(code):
    """Rend les champs d'un preset, ou leve ValueError. Ne porte pas le nom."""
    if not isinstance(code, str):
        raise ValueError("code absent")
    code = code.strip()
    if not code:
        raise ValueError("code vide")
    if len(code) > CODE_MAX_LEN:
        raise ValueError("code trop long")
    parts = code.split("-")
    if len(parts) != 4 + len(CODE_FIELDS):
        raise ValueError("code incomplet ou mal decoupe")
    if parts[0].upper() != CODE_PREFIX:
        raise ValueError("prefixe attendu %s" % CODE_PREFIX)

    if parts[1] not in _FLAG_VALUES:
        raise ValueError("drapeaux de forme invalides")
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
            elif msg.message == WM_USER_REREGISTER:
                self._register_all()

    def change_modifier(self, modifier_flags):
        self._mod = modifier_flags
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_USER_REREGISTER, 0, 0)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)


# ─── Profils par jeu ─────────────────────────────────────────────────────────

class ProfileWatcher:
    """Bascule de preset selon le jeu au premier plan.

    Sonde en continu, meme sans profil enregistre : c'est ce sondage qui retient
    le dernier jeu vu, dont le bouton « associer » a besoin pour creer le tout
    premier profil. Trois appels Win32 toutes les deux secondes.
    """

    INTERVAL_MS = 2000

    def __init__(self, root, config, on_switch):
        self.root = root
        self.config = config
        self.on_switch = on_switch
        self.last_seen = None      # dernier executable etranger observe
        self.manual_preset = config["preset"]
        self.active = None         # profil actuellement declenche
        self.applied = None        # preset que nous pilotons, None si on a lache
        self.root.after(0, self._tick)

    def _tick(self):
        exe = foreground_exe()
        if exe:
            self.last_seen = exe
            target = self.config["profiles"].get(exe)
            if target is not None:
                if self.active != exe:
                    if self.active is None:
                        # on quitte le bureau : retenir le preset choisi a la main
                        self.manual_preset = self.config["preset"]
                    self.active = exe
                    self.applied = target
                    self.on_switch(target)
                elif self.applied is not None and self.config["preset"] != self.applied:
                    # tray, raccourci ou Enregistrer ont change le preset pendant
                    # le jeu : le geste humain prime, on cesse de piloter jusqu'a
                    # ce qu'on sorte de ce jeu, et ce choix devient le choix manuel
                    # a restaurer plus tard.
                    self.applied = None
                    self.manual_preset = self.config["preset"]
            elif self.active is not None:
                driving = self.applied is not None
                self.active = None
                self.applied = None
                if driving:
                    # on ne restaure que si l'utilisateur n'a pas deja repris la main
                    self.on_switch(self.manual_preset)
        self.root.after(self.INTERVAL_MS, self._tick)

    def forget(self, exe):
        if self.active == exe:
            self.active = None
            self.applied = None


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
        self.hotkeys = None
        self.watcher = None
        self.win = None
        self.editing = config["preset"]

    def toggle(self):
        if self.win and self.win.winfo_exists():
            self.win.destroy()
            self.win = None
            return
        # le preset a pu changer depuis la derniere ouverture (raccourci, tray,
        # profil) : repartir de celui qui est reellement actif, sinon Appliquer
        # ramenerait le viseur a un preset perime.
        self.editing = _clamp_index(self.config["preset"], len(self.config["presets"]) - 1)
        self._build()

    def _build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Viseur — Paramètres")
        self.win.geometry("460x820")
        self.win.resizable(False, False)
        self.win.configure(bg=BG)
        self.win.attributes("-topmost", True)
        self._icon_photo = ImageTk.PhotoImage(create_tray_icon_image(32))
        self.win.iconphoto(False, self._icon_photo)
        self.win.protocol("WM_DELETE_WINDOW", lambda: (self.win.destroy(), setattr(self, "win", None)))

        # ── Onglets ──
        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", padx=15, pady=(12, 10))
        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True)

        self.tab_btns = {}
        self.tabs = {}
        for key, label in (("viseur", "Viseur"), ("profils", "Profils"), ("general", "Général")):
            btn = tk.Button(bar, text=label, command=lambda k=key: self._show_tab(k),
                            bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                            relief="flat", bd=0, font=FONT, padx=16, pady=4, cursor="hand2")
            btn.pack(side="left", padx=(0, 3))
            self.tab_btns[key] = btn
            self.tabs[key] = tk.Frame(body, bg=BG)

        self._build_tab_viseur(self.tabs["viseur"])
        self._build_tab_profils(self.tabs["profils"])
        self._build_tab_general(self.tabs["general"])

        # ── Barre d'action commune ──
        bf = tk.Frame(self.win, bg=BG)
        bf.pack(fill="x", padx=15, pady=(6, 12))
        tk.Button(bf, text="Appliquer", command=self._apply, bg=BG3, fg=FG,
                  font=FONT, relief="flat", padx=14, pady=3, cursor="hand2").pack(side="left")
        tk.Button(bf, text="Enregistrer", command=self._save, bg=ACCENT, fg="#1A1207",
                  font=FONT_B, relief="flat", padx=14, pady=3,
                  cursor="hand2").pack(side="left", padx=(8, 0))
        self.status = tk.Label(bf, text="", bg=BG, fg=FG2, font=FONT_S, anchor="e")
        self.status.pack(side="right", fill="x", expand=True)

        self._show_tab("viseur")
        self._load_preset(self.editing)
        self.win.lift()
        self.win.focus_force()

    # ── Onglet « Viseur » ────────────────────────────────────────────────────

    def _build_tab_viseur(self, tab):
        self._section(tab, "Écran", 0)
        f = tk.Frame(tab, bg=BG)
        f.pack(fill="x", padx=15, pady=(0, 8))

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

        self._section(tab, "Presets", 0)
        pf = tk.Frame(tab, bg=BG)
        pf.pack(fill="x", padx=15, pady=(0, 8))

        self.preset_btns = []
        for i in range(10):
            short = self.config["presets"][i]["name"][:6]
            btn = tk.Button(
                pf, text=f"{i+1}\n{short}", width=5, height=2,
                command=lambda idx=i: self._select_preset(idx),
                bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                relief="flat", font=FONT_S, bd=0,
            )
            btn.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="ew")
            self.preset_btns.append(btn)
        for c in range(5):
            pf.columnconfigure(c, weight=1)
        self._highlight_preset()

        self._section(tab, "Paramètres", 0)
        sf = tk.Frame(tab, bg=BG2, bd=1, relief="flat")
        sf.pack(fill="x", padx=15, pady=(0, 8))

        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(row, text="Nom :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(row, textvariable=self.name_var, bg=BG3, fg=FG, insertbackground=FG,
                 font=FONT, relief="flat", bd=2).pack(side="left", fill="x", expand=True)

        row = tk.Frame(sf, bg=BG2)
        row.pack(fill="x", padx=10, pady=4)
        tk.Label(row, text="Forme :", bg=BG2, fg=FG, font=FONT, width=10, anchor="w").pack(side="left")
        self.cross_var = tk.BooleanVar()
        self.circle_var = tk.BooleanVar()
        self.dot_var = tk.BooleanVar()
        for text, var in [("Croix", self.cross_var), ("Cercle", self.circle_var),
                          ("Point", self.dot_var)]:
            tk.Checkbutton(row, text=text, variable=var, bg=BG2, fg=FG,
                           selectcolor=BG3, activebackground=BG2, activeforeground=FG,
                           font=FONT, command=self._on_change).pack(side="left", padx=(0, 10))

        self.colors = {}
        for label, which in (("Couleur :", "color"), ("Contour :", "outline")):
            row = tk.Frame(sf, bg=BG2)
            row.pack(fill="x", padx=10, pady=4)
            tk.Label(row, text=label, bg=BG2, fg=FG, font=FONT,
                     width=10, anchor="w").pack(side="left")
            swatch = tk.Canvas(row, width=30, height=20, bd=1, relief="solid", cursor="hand2")
            swatch.pack(side="left", padx=(0, 5))
            swatch.bind("<Button-1>", lambda e, w=which: self._pick_color(w))
            value = tk.Label(row, bg=BG2, fg=FG2, font=FONT_MONO)
            value.pack(side="left")
            self.colors[which] = (swatch, value)

        self.sliders = {}
        for label, key in (("Taille", "size"), ("Épaisseur", "thickness"),
                           ("Espace", "gap"), ("Rayon point", "dot_radius")):
            lo, hi = SLIDER_RANGES[key]
            row = tk.Frame(sf, bg=BG2)
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=f"{label} :", bg=BG2, fg=FG, font=FONT,
                     width=10, anchor="w").pack(side="left")
            val_label = tk.Label(row, text="0", bg=BG2, fg=ACCENT, font=FONT_MONO,
                                 width=3, anchor="e")
            val_label.pack(side="right")
            scale = tk.Scale(
                row, from_=lo, to=hi, orient="horizontal", showvalue=False,
                bg=BG2, fg=FG, troughcolor=BG3, activebackground=ACCENT,
                highlightthickness=0, bd=0, length=200,
                command=lambda v, lbl=val_label: (lbl.config(text=str(int(float(v)))),
                                                  self._on_change()),
            )
            scale.pack(side="left", fill="x", expand=True, padx=(5, 5))
            self.sliders[key] = (scale, val_label)

        tk.Frame(sf, bg=BG2, height=8).pack()

        self._section(tab, "Aperçu", 0)
        pv = tk.Frame(tab, bg=BG)
        pv.pack(pady=(0, 8))
        self.preview = tk.Canvas(pv, width=120, height=120, bg="#111111",
                                 highlightthickness=1, highlightbackground=BG3)
        self.preview.pack()

        self._section(tab, "Code de viseur", 0)
        cf = tk.Frame(tab, bg=BG)
        cf.pack(fill="x", padx=15, pady=(0, 8))
        self.code_var = tk.StringVar()
        tk.Entry(cf, textvariable=self.code_var, bg=BG3, fg=FG, insertbackground=FG,
                 font=FONT_MONO, relief="flat", bd=2).pack(fill="x", pady=(0, 4))
        btns = tk.Frame(cf, bg=BG)
        btns.pack(fill="x")
        tk.Button(btns, text="Copier", command=self._copy_code, bg=BG3, fg=FG,
                  font=FONT_S, relief="flat", padx=10, cursor="hand2").pack(side="left")
        tk.Button(btns, text="Coller", command=self._paste_code, bg=BG3, fg=FG,
                  font=FONT_S, relief="flat", padx=10,
                  cursor="hand2").pack(side="left", padx=(4, 0))
        tk.Button(btns, text="Importer dans ce preset", command=self._import_code,
                  bg=BG3, fg=FG, font=FONT_S, relief="flat", padx=10,
                  cursor="hand2").pack(side="left", padx=(4, 0))

    # ── Onglet « Profils » ───────────────────────────────────────────────────

    def _build_tab_profils(self, tab):
        self._section(tab, "Bascule automatique", 0)
        tk.Label(tab, text="Le preset associé s'active dès que le jeu passe au premier plan,\n"
                           "et le réglage manuel revient quand on en sort.",
                 bg=BG, fg=FG2, font=FONT_S, justify="left",
                 anchor="w").pack(fill="x", padx=15, pady=(0, 8))

        add = tk.Frame(tab, bg=BG)
        add.pack(fill="x", padx=15, pady=(0, 8))
        self.seen_label = tk.Label(add, text="Aucun jeu détecté pour l'instant",
                                   bg=BG2, fg=FG, font=FONT_MONO, anchor="w", padx=8, pady=5)
        self.seen_label.pack(fill="x", pady=(0, 4))
        tk.Button(add, text="Associer ce jeu au preset affiché", command=self._add_profile,
                  bg=BG3, fg=FG, font=FONT, relief="flat", padx=12, pady=3,
                  cursor="hand2").pack(fill="x")

        self._section(tab, "Associations", 6)
        self.profiles_frame = tk.Frame(tab, bg=BG)
        self.profiles_frame.pack(fill="both", expand=True, padx=15, pady=(0, 8))

    def _refresh_profiles(self):
        for child in self.profiles_frame.winfo_children():
            child.destroy()

        seen = self.watcher.last_seen if self.watcher else None
        self.seen_label.config(text=seen or "Aucun jeu détecté pour l'instant")

        profiles = self.config["profiles"]
        if not profiles:
            tk.Label(self.profiles_frame, text="Aucune association.",
                     bg=BG, fg=FG2, font=FONT_S, anchor="w").pack(fill="x")
            return

        for exe in sorted(profiles):
            idx = profiles[exe]
            row = tk.Frame(self.profiles_frame, bg=BG2)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=exe, bg=BG2, fg=FG, font=FONT_MONO,
                     anchor="w", padx=8, pady=4).pack(side="left", fill="x", expand=True)
            tk.Label(row, text=f"{idx + 1}. {self.config['presets'][idx]['name']}",
                     bg=BG2, fg=ACCENT, font=FONT_S, anchor="e", padx=8).pack(side="left")
            tk.Button(row, text="✕", command=lambda e=exe: self._remove_profile(e),
                      bg=BG2, fg=FG2, activebackground=BG3, activeforeground=FG,
                      font=FONT_S, relief="flat", bd=0, padx=8,
                      cursor="hand2").pack(side="right")

    def _add_profile(self):
        seen = self.watcher.last_seen if self.watcher else None
        if not seen:
            self._set_status("Passe d'abord sur ton jeu, puis reviens ici.")
            return
        self.config["profiles"][seen] = self.editing
        self._refresh_profiles()
        self._set_status(f"{seen} → preset {self.editing + 1} — Enregistrer pour le garder")

    def _remove_profile(self, exe):
        self.config["profiles"].pop(exe, None)
        if self.watcher:
            self.watcher.forget(exe)
        self._refresh_profiles()
        self._set_status(f"{exe} dissocié — Enregistrer pour le garder")

    # ── Onglet « Général » ───────────────────────────────────────────────────

    def _build_tab_general(self, tab):
        self._section(tab, "Raccourcis", 0)
        hf = tk.Frame(tab, bg=BG)
        hf.pack(fill="x", padx=15, pady=(0, 8))
        tk.Label(hf, text="Modifier :", bg=BG, fg=FG, font=FONT, anchor="w").pack(side="left")
        self.modifier_var = tk.StringVar(value=self.config.get("modifier", "Ctrl+Alt"))
        mod_menu = tk.OptionMenu(hf, self.modifier_var, *MODIFIER_CHOICES.keys())
        mod_menu.config(bg=BG3, fg=FG, activebackground=BG2, activeforeground=FG,
                        highlightthickness=0, font=FONT_S, relief="flat")
        mod_menu["menu"].config(bg=BG3, fg=FG, activebackground=ACCENT, font=FONT_S)
        mod_menu.pack(side="left", padx=(8, 0), fill="x", expand=True)

        tk.Label(tab, text="S, H, Q et 1 à 0 se combinent avec ce modificateur.",
                 bg=BG, fg=FG2, font=FONT_S, anchor="w").pack(fill="x", padx=15, pady=(0, 8))

        self._section(tab, "Démarrage", 6)
        self.startup_var = tk.BooleanVar(value=startup_enabled())
        tk.Checkbutton(tab, text="Lancer Viseur à l'ouverture de session",
                       variable=self.startup_var, command=self._toggle_startup,
                       bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                       activeforeground=FG, font=FONT,
                       anchor="w").pack(fill="x", padx=15)
        tk.Label(tab, text="Ajoute un raccourci dans le dossier Démarrage.\n"
                           "Aucune écriture dans le registre.",
                 bg=BG, fg=FG2, font=FONT_S, justify="left",
                 anchor="w").pack(fill="x", padx=15, pady=(2, 8))

    def _toggle_startup(self):
        wanted = self.startup_var.get()
        actual = set_startup(wanted)
        self.startup_var.set(actual)
        if actual == wanted:
            self._set_status("Démarrage activé" if actual else "Démarrage désactivé")
        else:
            self._set_status("Impossible de modifier le démarrage")

    # ── Codes de viseur ──────────────────────────────────────────────────────

    def _copy_code(self):
        code = preset_to_code(self._read_current())
        self.code_var.set(code)
        self.win.clipboard_clear()
        self.win.clipboard_append(code)
        self._set_status("Code copié")

    def _paste_code(self):
        try:
            self.code_var.set(self.win.clipboard_get().strip())
            self._set_status("Code collé, clique sur Importer")
        except Exception:
            self._set_status("Presse-papiers vide")

    def _import_code(self):
        try:
            values = code_to_preset(self.code_var.get())
        except ValueError as err:
            self._set_status("Code refusé : %s" % err)
            return
        self.cross_var.set(values["show_cross"])
        self.circle_var.set(values["show_circle"])
        self.dot_var.set(values["show_dot"])
        for which in self.colors:
            self._set_color(which, values[which])
        for key in CODE_FIELDS:
            self.sliders[key][0].set(values[key])
        self._update_preview()
        self._set_status("Code importé — Enregistrer pour le garder")

    def _set_color(self, which, hex_color):
        swatch, value = self.colors[which]
        swatch.config(bg=hex_color)
        value.config(text=hex_color)

    def _set_status(self, text):
        if getattr(self, "status", None):
            self.status.config(text=text[:80])

    def _section(self, parent, text, pady_top=5):
        tk.Label(parent, text=text, bg=BG, fg=ACCENT, font=FONT_B,
                 anchor="w").pack(fill="x", padx=15, pady=(pady_top, 2))

    def _show_tab(self, key):
        for name, frame in self.tabs.items():
            if name == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for name, btn in self.tab_btns.items():
            active = name == key
            btn.config(bg=ACCENT if active else BG3, fg="#1A1207" if active else FG)
        if key == "profils":
            self._refresh_profiles()

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
        for which in self.colors:
            self._set_color(which, p[which])
        for key, (scale, val_label) in self.sliders.items():
            scale.set(p[key])
            val_label.config(text=str(p[key]))
        self.code_var.set(preset_to_code(p))
        self._update_preview()

    def _read_current(self):
        return {
            "name": self.name_var.get(),
            "show_cross": self.cross_var.get(),
            "show_circle": self.circle_var.get(),
            "show_dot": self.dot_var.get(),
            "color": self.colors["color"][1].cget("text"),
            "outline": self.colors["outline"][1].cget("text"),
            "size": int(self.sliders["size"][0].get()),
            "thickness": int(self.sliders["thickness"][0].get()),
            "gap": int(self.sliders["gap"][0].get()),
            "dot_radius": int(self.sliders["dot_radius"][0].get()),
        }

    def _on_change(self, *_):
        self._update_preview()

    def _pick_color(self, which):
        current = self.colors[which][1].cget("text")
        result = colorchooser.askcolor(color=current, title="Choisir une couleur")
        if result and result[1]:
            if not valid_color(result[1]):
                self._set_status("%s rendrait le viseur invisible" % CHROMA_KEY)
                return
            self._set_color(which, result[1])
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

        new_mod = self.modifier_var.get()
        if new_mod != self.config.get("modifier") and self.hotkeys:
            self.config["modifier"] = new_mod
            self.hotkeys.change_modifier(MODIFIER_CHOICES[new_mod])

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
    settings.watcher = ProfileWatcher(root, config, switch_preset)
    tray = TrayIcon(root, config, overlay, settings, shutdown)

    root.mainloop()


if __name__ == "__main__":
    main()
