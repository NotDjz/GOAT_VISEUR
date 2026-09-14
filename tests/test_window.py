"""The settings window icon, both what it carries and what the taskbar shows.

Those are two different things, and confusing them cost a real bug: `WM_GETICON`
returned valid handles while the user saw a blank page icon in the taskbar, because
Windows had cached a stale icon for that executable path. Battery 5 proves the
window carries the icon; battery 7 proves the executable carries the icon the
taskbar resolves from, which is as close to the taskbar as source can get.

Opens a real window on the second screen, so it needs a desktop session. These
batteries have teeth: `iconphoto` looked like it worked while handing
Windows a single 32px image to shrink, and setting the icon before the window was
mapped looked like it worked while landing it on a handle Tk then replaced.
"""
import ctypes
import io
import os
import struct
import tkinter as tk
from ctypes import wintypes as wt

from _harness import Checks, load_module, open_settings, run, test_screen

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
shell32 = ctypes.windll.shell32
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


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


# The crosshair's fill, from crosshair.pyw and generate_icon.py, with the slack that
# antialiasing needs. The tolerance stays test-local, but the colour is not restated:
# a filter that hard-codes its own numbers drifts away from the icon it describes.
CROSSHAIR_GREEN = (0, 204, 102)
GREEN_TOLERANCE = 20


def is_crosshair_green(red, green, blue):
    """Our green, and not the other green a taskbar holds.

    The red channel is what separates them: Spotify sits near rgb(30, 215, 96) and
    fails this, measured, while the crosshair and its antialiasing pass.
    """
    want_r, want_g, want_b = CROSSHAIR_GREEN
    return (abs(red - want_r) < GREEN_TOLERANCE
            and abs(green - want_g) < GREEN_TOLERANCE
            and abs(blue - want_b) < GREEN_TOLERANCE)


def ico_entry_sizes(path):
    """The sizes a .ico file really contains, read from its own directory.

    `LoadImageW` scales the nearest entry to whatever size is asked for, so it can
    never tell a hand-drawn 16px entry from a 256px one shrunk down: ask it for
    77x77 and it hands back a 77x77 icon. Only the file's directory answers which
    entries exist, which is what the shell picks among.
    """
    with io.open(path, "rb") as handle:
        header = handle.read(6)
        if len(header) < 6:
            return []
        reserved, kind, count = struct.unpack("<HHH", header)
        if reserved or kind != 1:
            return []
        sizes = []
        for _ in range(count):
            entry = handle.read(16)
            if len(entry) < 16:
                break
            sizes.append((entry[0] or 256, entry[1] or 256))
    return sizes


def icon_bgra(handle):
    """(width, height, BGRA bytes) for an HICON, or None. Frees what it queries.

    One helper rather than two, so the GetIconInfo dance and the "bottom-up unless
    biHeight is negative" detail live in exactly one place.
    """
    if not handle:
        return None
    info = ICONINFO()
    if not user32.GetIconInfo(ctypes.c_void_p(handle), ctypes.byref(info)):
        return None
    # Every GDI call is checked. Unchecked, a failed read leaves the buffer zeroed
    # and hands back a plausible all-black icon, which scores zero green and is
    # indistinguishable from "this is not our crosshair" - a failure that reads as
    # a passing control.
    bitmap = BITMAP()
    ok = gdi32.GetObjectW(ctypes.c_void_p(info.hbmColor), ctypes.sizeof(BITMAP),
                          ctypes.byref(bitmap))
    width, height = bitmap.bmWidth, bitmap.bmHeight
    pixels = None
    if ok and width > 0 and height > 0:
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth, header.biHeight = width, -height
        header.biPlanes, header.biBitCount = 1, 32
        buf = (ctypes.c_ubyte * (width * height * 4))()
        dc = user32.GetDC(None)
        read = gdi32.GetDIBits(dc, ctypes.c_void_p(info.hbmColor), 0, height, buf,
                               ctypes.byref(header), 0)
        user32.ReleaseDC(None, dc)
        if read == height:
            pixels = bytes(buf)
    gdi32.DeleteObject(ctypes.c_void_p(info.hbmColor))
    gdi32.DeleteObject(ctypes.c_void_p(info.hbmMask))
    if pixels is None:
        return None
    return (width, height, pixels)


def icon_size(handle):
    """The pixel size of an HICON, or None."""
    got = icon_bgra(handle)
    return got[:2] if got else None


def icon_green(handle):
    """How many pixels of an HICON are the crosshair's own green.

    The red channel is what separates it from the other green a taskbar is likely
    to hold: Spotify sits near rgb(30, 215, 96) and scores zero here, measured,
    while the crosshair scores about seventy.
    """
    got = icon_bgra(handle)
    if not got:
        return 0
    px = got[2]          # BGRA
    return sum(1 for i in range(0, len(px), 4)
               if is_crosshair_green(px[i + 2], px[i + 1], px[i]))


def exe_icons(path):
    """The large and small HICONs an executable exposes, as the shell reads them.

    This is what the taskbar draws for a window: it resolves the button's icon from
    the executable, not from WM_SETICON.
    """
    big = (ctypes.c_void_p * 1)()
    small = (ctypes.c_void_p * 1)()
    if not shell32.ExtractIconExW(path, 0, big, small, 1):
        return []
    return [h for h in (big[0], small[0]) if h]


def icon_file_handles(path, sizes=(16, 32)):
    """HICONs loaded straight out of a .ico file, one per requested size."""
    out = []
    for size in sizes:
        handle = user32.LoadImageW(None, path, 1, size, size, 0x0010)
        if handle:
            out.append(handle)
    return out


def icons_of(cross, win):
    hwnd = cross.real_hwnd(win)
    return (user32.SendMessageW(hwnd, WM_GETICON, 0, 0) or 0,
            user32.SendMessageW(hwnd, WM_GETICON, 1, 0) or 0)


def main():
    cross = load_module()
    root, settings, _config = open_settings(cross)
    monitors = cross.get_monitors()
    screen = test_screen(monitors)

    c = Checks("BATTERY 5 - the window carries the icon")
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

    c.section("BATTERY 5b - control: the old path gives one image for both")
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

    c.section("BATTERY 6 - the icon handles are cached, not reloaded per open")
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

    c.section("BATTERY 6b - control: an uncached load returns fresh handles")
    cached = [h for _, h in cross._window_icons]
    fresh = [cross.user32.LoadImageW(None, cross.ICON_FILE, cross.IMAGE_ICON,
                                     size, size, cross.LR_LOADFROMFILE)
             for size in (want_small, want_big)]
    c.note("cached %s   freshly loaded %s"
           % ([hex(h) for h in cached], [hex(h) for h in fresh]))
    c("control: loading again gives different handles",
      all(h not in cached for h in fresh), True)

    c.section("BATTERY 7 - the icon the taskbar resolves from")
    # Measured, and the distinction cost a real bug: the taskbar button does NOT
    # use WM_SETICON. It draws the executable's own icon resource, the one
    # build.bat passes with --icon. Battery 5 above checks what the window carries,
    # which is what the title bar and Alt+Tab use. Run from source there is no exe
    # and the taskbar shows Python's icon, whatever the window declares.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ico = os.path.join(repo, "screenscope.ico")

    # Leg 1 works from the tracked tree, so it still measures on a fresh clone.
    # It reads the file's directory rather than loading it: LoadImageW scales the
    # nearest entry to any size asked for, so it would report success on an icon
    # holding nothing but a single 256px entry.
    sizes = ico_entry_sizes(ico)
    c.note("entries really in screenscope.ico: %s" % (sizes or "none"))
    c("the 16px entry is drawn, not scaled from a bigger one", (16, 16) in sizes, True)
    c("and so is the 32px one", (32, 32) in sizes, True)
    # Control: the loader cannot tell those apart, which is why the check above
    # reads the file. If this ever stops returning a handle, the reasoning behind
    # leg 1 has changed and the check above needs revisiting.
    absent = icon_file_handles(ico, sizes=(77,))
    c("control: the loader happily invents a size the file lacks",
      [icon_size(h) for h in absent], [(77, 77)])
    for handle in absent:
        user32.DestroyIcon(ctypes.c_void_p(handle))

    handles = icon_file_handles(ico)
    green = sum(icon_green(h) for h in handles)
    c.note("loaded at 16 and 32: crosshair-green pixels %d" % green)
    c("both sizes load", len(handles), 2)
    c("and they are our crosshair", green > 40, True)
    for handle in handles:
        user32.DestroyIcon(ctypes.c_void_p(handle))

    with io.open(os.path.join(repo, "build.bat"), encoding="utf-8") as handle:
        build = handle.read()
    c("build.bat still dresses the exe with it", "--icon screenscope.ico" in build, True)

    # Leg 2 confirms end to end on a built exe.
    exe = os.path.join(repo, "dist", "ScreenScope.exe")
    if not os.path.exists(exe):
        c.skip("no dist exe to confirm against, run build.bat")
    else:
        exe_handles = exe_icons(exe)
        c("the exe exposes a large and a small icon", len(exe_handles), 2)
        exe_green = sum(icon_green(h) for h in exe_handles)
        c.note("the built exe: %s, crosshair-green pixels: %d"
               % ([icon_size(h) for h in exe_handles], exe_green))
        c("and it is our crosshair, not a default", exe_green > 40, True)
        for handle in exe_handles:
            user32.DestroyIcon(ctypes.c_void_p(handle))

    # Control: an executable nobody dressed must score nothing. Several candidates,
    # because the System32 notepad is a Store stub missing on some installs, and a
    # control that quietly disappears is the shape this project forbids. The
    # extraction itself is asserted too: no handles means no green, which would
    # pass this control without measuring anything.
    other = next((path for path in (
        os.path.join(os.environ.get("SystemRoot", "C:" + os.sep + "Windows"),
                     "System32", "notepad.exe"),
        os.path.join(os.environ.get("SystemRoot", "C:" + os.sep + "Windows"),
                     "System32", "cmd.exe"),
        os.path.join(os.environ.get("SystemRoot", "C:" + os.sep + "Windows"),
                     "explorer.exe")) if os.path.exists(path)), None)
    c("a control executable was found", other is not None, True)
    if other:
        control_handles = exe_icons(other)
        c("control: it really exposed icons to measure", len(control_handles) > 0, True)
        control_green = sum(icon_green(h) for h in control_handles)
        c.note("the same measurement on %s: %d green"
               % (os.path.basename(other), control_green))
        c("control: an undressed exe scores no crosshair green",
          control_green > 40, False)
        for handle in control_handles:
            user32.DestroyIcon(ctypes.c_void_p(handle))

    settings.win.destroy()
    root.destroy()
    os.remove(cross.CONFIG_FILE)
    return c.finish()


run(main)
