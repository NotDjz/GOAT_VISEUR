# Screen Scope — Crosshair Overlay

A crisp crosshair drawn on top of any game, centered on the monitor you choose.
Ten presets, no installer — one exe and its config file next to it.

## Usage

Run `ScreenScope.exe` — the crosshair appears at the centre of the screen.
Right-click the system tray icon for the menu.

## Hotkeys

| Hotkey | Action |
|--------|--------|
| `Mod+S` | Open or close the settings window |
| `Mod+H` | Hide or show the crosshair |
| `Mod+1`–`0` | Switch preset (1–10) |
| `Mod+Q` | Quit |

`Mod` is `Ctrl+Alt` by default. If one of these clashes with your game, pick
another one in the **Shortcuts** tab — `Ctrl+Shift`, `Alt+Shift` or
`Ctrl+Alt+Shift`. It applies straight away, and the tab tells you if Windows
refused a key because another application already holds it.

## Settings

Two tabs. **Crosshair** holds everything about the crosshair itself on a single
page: pick the screen, pick a preset, name it, shape it, and save. Settings that
don't apply are grayed out — `Gap` means nothing without a cross, and `Dot size`
means nothing without a dot. **Shortcuts** holds the modifier.

## Crosshair codes

Every preset boils down to a short code you can share:

```
VSR1-5-FFFFFF-690F96-13-1-3-1
```

*Copy* puts the current preset's code on the clipboard. *Paste* reads a code from
the clipboard and applies it to the selected preset — then *Save* to keep it.
Invalid codes are refused with a reason, and nothing is changed.

## Upgrading from an earlier build

Two earlier features are gone: per-game profiles and the run-at-startup checkbox.
If you had ticked that checkbox, the shortcut it created is still there and Screen Scope
will keep starting with Windows — delete
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Viseur.lnk` if you
don't want that. A leftover `profiles` key in `config.json` is dropped on next save.

## Rebuilding (optional)

Needs Python 3 and `py -m pip install -r requirements.txt`

1. `py generate_icon.py`
2. `build.bat`
3. The executable lands in `dist\ScreenScope.exe`
