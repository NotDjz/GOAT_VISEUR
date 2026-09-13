"""The overlay must stay click-through.

`real_hwnd()` replaced a `GetParent` call here. Tk's `winfo_id()` is not the window
Windows shows — an `overrideredirect` Toplevel's id is a child of the real frame —
so resolving the wrong handle puts `WS_EX_TRANSPARENT` on the child and the overlay
starts swallowing clicks in whatever game is underneath. Silent, and only noticed
in the middle of a match, which is why it gets its own battery.
"""
import ctypes
import io
import json
import os
import time
import tkinter as tk

from _harness import Checks, load_module, run, test_screen

user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]


def main():
    cross = load_module()
    monitors = cross.get_monitors()
    screen = test_screen(monitors)
    io.open(cross.CONFIG_FILE, "w", encoding="utf-8").write(
        json.dumps({"monitor": screen, "preset": 0, "modifier": "Ctrl+Shift"}))
    config = cross.load_config(len(monitors))

    root = tk.Tk()
    root.withdraw()
    overlay = cross.Overlay(root, config, monitors)
    root.update()
    root.update_idletasks()

    # _make_click_through is deferred 500 ms after the overlay is built
    deadline = time.time() + 3
    while not hasattr(overlay, "hwnd") and time.time() < deadline:
        root.update()
        time.sleep(0.05)

    c = Checks("BATTERY 6 - the overlay is click-through")
    c.note("testing on screen %d of %d" % (screen, len(monitors)))
    if not hasattr(overlay, "hwnd"):
        c("the deferred _make_click_through ran", False, True)
        overlay.win.destroy()
        root.destroy()
        os.remove(cross.CONFIG_FILE)
        return c.finish()

    style = user32.GetWindowLongPtrW(ctypes.c_void_p(overlay.hwnd), cross.GWL_EXSTYLE)
    c.note("overlay hwnd=%s  ex-style=0x%08X" % (hex(overlay.hwnd), style & 0xFFFFFFFF))
    c("the resolved handle is the frame, not the tk child",
      overlay.hwnd != overlay.win.winfo_id(), True)
    c("WS_EX_TRANSPARENT is set on it", bool(style & cross.WS_EX_TRANSPARENT), True)

    c.section("BATTERY 6b - control: the tk child must NOT carry the flag")
    # This is what the failure looks like: had real_hwnd() fallen back to
    # winfo_id(), the flag would land here and the frame would keep taking clicks.
    child = user32.GetWindowLongPtrW(ctypes.c_void_p(overlay.win.winfo_id()),
                                     cross.GWL_EXSTYLE)
    c.note("tk child hwnd=%s  ex-style=0x%08X"
           % (hex(overlay.win.winfo_id()), child & 0xFFFFFFFF))
    c("control: the child is untouched", bool(child & cross.WS_EX_TRANSPARENT), False)

    overlay.win.destroy()
    root.destroy()
    os.remove(cross.CONFIG_FILE)
    return c.finish()


run(main)
