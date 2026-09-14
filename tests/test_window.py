"""The settings window: its icon, and the room the AltGr warning needs.

Opens a real window on the second screen, so it needs a desktop session. The icon
batteries are the ones with teeth: `iconphoto` looked like it worked while handing
Windows a single 32px image to shrink, and setting the icon before the window was
mapped looked like it worked while landing it on a handle Tk then replaced.
"""
import ctypes
import os
import tkinter as tk
from ctypes import wintypes as wt

from _harness import Checks, load_module, run, test_screen, write_config

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
WM_GETICON = 0x007F
SM_CXICON, SM_CXSMICON = 11, 49


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wt.WORD), ("bmBitsPixel", wt.WORD),
                ("bmBits", ctypes.c_void_p)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


def icon_size(handle):
    """The pixel size of an HICON, or None. Frees the bitmaps it queries."""
    if not handle:
        return None
    info = ICONINFO()
    if not user32.GetIconInfo(ctypes.c_void_p(handle), ctypes.byref(info)):
        return None
    bitmap = BITMAP()
    gdi32.GetObjectW(ctypes.c_void_p(info.hbmColor), ctypes.sizeof(BITMAP),
                     ctypes.byref(bitmap))
    gdi32.DeleteObject(ctypes.c_void_p(info.hbmColor))
    gdi32.DeleteObject(ctypes.c_void_p(info.hbmMask))
    return (bitmap.bmWidth, bitmap.bmHeight)


def icons_of(cross, win):
    hwnd = cross.real_hwnd(win)
    return (user32.SendMessageW(hwnd, WM_GETICON, 0, 0) or 0,
            user32.SendMessageW(hwnd, WM_GETICON, 1, 0) or 0)


def main():
    cross = load_module()

    class StubOverlay:
        """Only what SettingsWindow reaches for; Save is never pressed here."""
        _draw_crosshair = cross.Overlay._draw_crosshair

        def apply(self):
            pass

    monitors = cross.get_monitors()
    screen = test_screen(monitors)
    config = write_config(
        cross, {"monitor": screen, "preset": 0, "modifier": "Ctrl+Shift"},
        len(monitors))

    root = tk.Tk()
    root.withdraw()
    settings = cross.SettingsWindow(root, config, monitors, StubOverlay())
    settings.toggle()
    root.update()
    root.update_idletasks()

    c = Checks("BATTERY 3 - the window icon")
    c.note("testing on screen %d of %d" % (screen, len(monitors)))
    small, big = icons_of(cross, settings.win)
    # Not hard-coded: Windows asks for bigger icons on a scaled display (20/40 at
    # 125%, 24/48 at 150%), and the loader has to follow rather than assume 16/32.
    want_small = user32.GetSystemMetrics(SM_CXSMICON)
    want_big = user32.GetSystemMetrics(SM_CXICON)
    c.note("this display asks for %dpx small / %dpx big" % (want_small, want_big))
    c("ICON_SMALL matches SM_CXSMICON", icon_size(small), (want_small, want_small))
    c("ICON_BIG matches SM_CXICON", icon_size(big), (want_big, want_big))
    c("two distinct handles, not one image reused", small != big, True)

    c.section("BATTERY 3b - control: the old path gives one image for both")
    # This is what the code did before: a single PhotoImage, which Windows shrinks
    # for the title bar. If this control ever matches the real path, the real path
    # has quietly regressed to it.
    control = tk.Toplevel(root)
    control.geometry("200x100+%d+300" % (monitors[screen]["x"] + 200))
    photo = cross.ImageTk.PhotoImage(cross.create_tray_icon_image(32))
    control.iconphoto(False, photo)
    control.update()
    c_small, c_big = icons_of(cross, control)
    c.note("iconphoto -> %s / %s, sizes %s / %s"
           % (hex(c_small), hex(c_big), icon_size(c_small), icon_size(c_big)))
    c("control: iconphoto uses ONE handle for both", c_small == c_big, True)
    control.destroy()

    c.section("BATTERY 4 - the icon handles are cached, not reloaded per open")
    first = icons_of(cross, settings.win)
    for _ in range(20):
        settings.toggle()
        root.update()
        settings.toggle()
        root.update()
    c("the window still has both icons after 20 cycles",
      all(icons_of(cross, settings.win)), True)
    c("the same handles are reused", icons_of(cross, settings.win), first)
    c("exactly two handles cached", len(cross._window_icons), 2)

    c.section("BATTERY 4b - control: an uncached load returns fresh handles")
    cached = [h for _, h in cross._window_icons]
    fresh = [cross.user32.LoadImageW(None, cross.ICON_FILE, cross.IMAGE_ICON,
                                     size, size, cross.LR_LOADFROMFILE)
             for size in (want_small, want_big)]
    c.note("cached %s   freshly loaded %s"
           % ([hex(h) for h in cached], [hex(h) for h in fresh]))
    c("control: loading again gives different handles",
      all(h not in cached for h in fresh), True)

    c.section("BATTERY 5 - the warning must fit the locked window height")
    # _lock_height() pins the window to the taller tab before the warning can ever
    # appear, so a warning that grows past it would be clipped with no way to scroll.
    #
    # Ctrl+Alt is gone from the choices and nothing left on the menu costs anything
    # on a French layout, so there is no way to raise a real warning here. The
    # invariant under test is "a full warning fits", not "this layout produces one",
    # so the detection is stubbed with the worst case it could ever report: every
    # registered key stolen.
    locked = settings.win.winfo_height()
    settings._show_tab("shortcuts")
    root.update_idletasks()
    quiet = settings.tabs["shortcuts"].winfo_reqheight()

    # setattr rather than plain assignment only because pyright refuses to type an
    # attribute write on a dynamically loaded module; same thing at runtime.
    real = cross.stolen_characters
    worst = sorted((chr(vk), "@") for vk in cross.HOTKEY_DEFS.values())
    setattr(cross, "stolen_characters", lambda _flags: worst)
    try:
        settings.modifier_var.set("Ctrl+Alt+Shift")
        settings._refresh_shortcuts()
        root.update_idletasks()
        warned = settings.tabs["shortcuts"].winfo_reqheight()
    finally:
        setattr(cross, "stolen_characters", real)

    chrome = settings.win.winfo_reqheight() - settings.tabs[settings.active_tab].winfo_reqheight()
    c.note("worst case is %d stolen keys" % len(worst))
    c.note("locked %dpx, tab %dpx quiet -> %dpx warned, needs %dpx with chrome"
           % (locked, quiet, warned, warned + chrome))
    c("the warning actually adds height", warned > quiet, True)
    c("even the worst-case warning still fits", warned + chrome <= locked, True)

    # Control: put the real detection back and the stub's height must go away. On a
    # layout that really does lose something to Ctrl+Alt+Shift the tab keeps a real
    # warning, so the check is "smaller than the worst case", not "back to quiet" -
    # otherwise this battery would fail on a German or Polish keyboard.
    settings._refresh_shortcuts()
    root.update_idletasks()
    restored = settings.tabs["shortcuts"].winfo_reqheight()
    if cross.stolen_characters(cross.MODIFIER_CHOICES["Ctrl+Alt+Shift"]):
        c.note("this layout does lose characters to Ctrl+Alt+Shift: a real warning stays")
        c("control: the stub no longer inflates the tab", restored < warned, True)
    else:
        c("control: the real detection leaves the tab at its quiet height",
          restored, quiet)

    settings.win.destroy()
    root.destroy()
    os.remove(cross.CONFIG_FILE)
    return c.finish()


run(main)
