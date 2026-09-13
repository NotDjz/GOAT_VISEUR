"""What a hotkey modifier costs the keyboard, and which one is the default.

Windows transmits AltGr as Ctrl+Alt, so registering Ctrl+Alt + a digit globally
takes the character AltGr puts on that key away from the user. These batteries
pin down that `stolen_characters()` actually detects it, and that the default
moved off Ctrl+Alt without silently rewriting anyone's saved choice.

Layout-dependent: the exact characters below are a French AZERTY's. On another
layout the counts differ, and the battery says so rather than failing blindly.
"""
import io
import json
import os

from _harness import Checks, load_module, run

AZERTY = {"0": "@", "2": "~", "3": "#", "4": "{",
          "5": "[", "6": "|", "7": "`", "8": "\\"}


def main():
    cross = load_module()
    c = Checks("BATTERY 1 - characters a modifier takes off the keyboard")

    french = (cross.user32.GetKeyboardLayout(0) & 0xFFFF) == 0x040C
    stolen = cross.stolen_characters(cross.MODIFIER_CHOICES["Ctrl+Alt"])
    c.note("Ctrl+Alt -> %s" % (", ".join("%s=%s" % kv for kv in stolen) or "nothing"))

    if french:
        c("Ctrl+Alt steals exactly the 8 AZERTY characters", dict(stolen), AZERTY)
    else:
        c.note("not a French layout (0x%04X): checking the shape, not the characters"
               % (cross.user32.GetKeyboardLayout(0) & 0xFFFF))
        c("every stolen key is one we actually register",
          all(ord(k) in cross.HOTKEY_DEFS.values() for k, _ in stolen), True)

    # Control: the modifiers that cost nothing must report nothing. Without this,
    # a function that returned a fixed list would pass the check above.
    for name in ("Ctrl+Shift", "Alt+Shift", "Ctrl+Alt+Shift"):
        c("control: %s steals nothing" % name,
          cross.stolen_characters(cross.MODIFIER_CHOICES[name]), [])

    c.section("BATTERY 1b - control: break the bit translation and the answer changes")
    # VkKeyScan's modifier bits (1 Shift, 2 Ctrl, 4 Alt) are NOT RegisterHotKey's
    # (MOD_ALT 1, MOD_SHIFT 4). Passing the flags straight through is the bug this
    # battery exists to catch, so the untranslated version must disagree.
    def untranslated(flags):
        layout = cross.user32.GetKeyboardLayout(0)
        keys = set(cross.HOTKEY_DEFS.values())
        found = {}
        for char in cross.SCANNED_CHARACTERS:
            scan = cross.user32.VkKeyScanExW(char, layout)
            if scan == -1:
                continue
            vk, state = scan & 0xFF, (scan >> 8) & 0x07
            if state == (flags & 0x07) and vk in keys:
                found.setdefault(chr(vk), char)
        return sorted(found.items())

    naive = untranslated(cross.MODIFIER_CHOICES["Ctrl+Alt"])
    c.note("untranslated(Ctrl+Alt) -> %s" % (naive or "nothing"))
    c("control: the untranslated version misses the conflict", naive != stolen, True)

    c.section("BATTERY 2 - the default modifier")

    def load(payload):
        io.open(cross.CONFIG_FILE, "w", encoding="utf-8").write(json.dumps(payload))
        return cross.load_config()["modifier"]

    c("no modifier key      -> the default", load({}), cross.DEFAULT_MODIFIER)
    c("unknown modifier     -> the default", load({"modifier": "Win+Z"}),
      cross.DEFAULT_MODIFIER)
    c("non-string modifier  -> the default", load({"modifier": 7}),
      cross.DEFAULT_MODIFIER)
    c("the default costs the keyboard nothing",
      cross.stolen_characters(cross.MODIFIER_CHOICES[cross.DEFAULT_MODIFIER]), [])

    # Control: a saved choice is indistinguishable from an accident, so it is kept.
    # If this ever fails, load_config() has started rewriting the user's setting.
    c("control: a saved Ctrl+Alt is KEPT, not migrated",
      load({"modifier": "Ctrl+Alt"}), "Ctrl+Alt")
    c("control: a saved Alt+Shift is KEPT", load({"modifier": "Alt+Shift"}),
      "Alt+Shift")
    os.remove(cross.CONFIG_FILE)

    return c.finish()


run(main)
