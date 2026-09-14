"""What a hotkey modifier costs the keyboard, and which one is the default.

Windows transmits AltGr as Ctrl+Alt, so registering Ctrl+Alt + a digit globally
takes the character AltGr puts on that key away from the user. Ctrl+Alt was
therefore removed from the offered modifiers entirely; these batteries pin down
that the detection still works, that nothing left on the menu costs anything, and
that a config written before the removal repairs itself instead of going on
stealing characters.

Layout-dependent: the exact characters below are a French AZERTY's. On another
layout the counts differ, and the battery says so rather than failing blindly.
"""
import os

from _harness import Checks, load_module, run, write_config

AZERTY = {"0": "@", "2": "~", "3": "#", "4": "{",
          "5": "[", "6": "|", "7": "`", "8": "\\"}


def main():
    cross = load_module()
    c = Checks("BATTERY 1 - the combination we removed is the one that costs characters")

    # Ctrl+Alt is no longer in MODIFIER_CHOICES, so the flags are built by hand:
    # the point of this battery is to keep proving *why* it is gone.
    ctrl_alt = cross.MOD_CONTROL | cross.MOD_ALT | cross.MOD_NOREPEAT
    french = (cross.user32.GetKeyboardLayout(0) & 0xFFFF) == 0x040C
    stolen = cross.stolen_characters(ctrl_alt)
    c.note("Ctrl+Alt would take: %s"
           % (", ".join("%s=%s" % kv for kv in stolen) or "nothing"))

    c("Ctrl+Alt is not offered any more", "Ctrl+Alt" in cross.MODIFIER_CHOICES, False)
    if french:
        c("Ctrl+Alt would take exactly the 8 AZERTY characters", dict(stolen), AZERTY)
    else:
        c.note("not a French layout (0x%04X): checking the shape, not the characters"
               % (cross.user32.GetKeyboardLayout(0) & 0xFFFF))
        c("every stolen key is one we actually register",
          all(ord(k) in cross.HOTKEY_DEFS.values() for k, _ in stolen), True)

    # Control: what is still on the menu must not cost what Ctrl+Alt cost. A layout
    # that does put something behind one of them is not a failure though: Polish
    # AltGr+Shift+S is S-acute and S is a registered hotkey, so Ctrl+Alt+Shift
    # legitimately reports a loss there. That is the case the Shortcuts warning
    # exists for, so the battery reports it rather than failing on correct code.
    free = []
    for name, flags in cross.MODIFIER_CHOICES.items():
        cost = cross.stolen_characters(flags)
        if cost:
            c.note("%s costs %d character(s) here, the warning will name them"
                   % (name, len(cost)))
        else:
            free.append(name)
            c("control: %s costs nothing here" % name, cost, [])
    # The invariant that holds on every layout: at least one offered modifier has
    # to be free, or the user has no safe choice left at all.
    c("at least one offered modifier is free of cost", bool(free), True)

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

    naive = untranslated(ctrl_alt)
    c.note("untranslated(Ctrl+Alt) -> %s" % (naive or "nothing"))
    if stolen:
        c("control: the untranslated version misses the conflict", naive != stolen, True)
    else:
        # Nothing behind AltGr on this layout, so both sides are empty and the
        # comparison would pass without measuring anything. Say so instead.
        c.note("nothing behind AltGr here: this control cannot discriminate, skipped")

    c.section("BATTERY 2 - the default, and the repair of older configs")

    def load(payload):
        return write_config(cross, payload)

    def modifier(payload):
        return load(payload)["modifier"]

    c("no modifier key      -> the default", modifier({}), cross.DEFAULT_MODIFIER)
    c("unknown modifier     -> the default", modifier({"modifier": "Win+Z"}),
      cross.DEFAULT_MODIFIER)
    c("non-string modifier  -> the default", modifier({"modifier": 7}),
      cross.DEFAULT_MODIFIER)
    c("the default is one of the offered choices",
      cross.DEFAULT_MODIFIER in cross.MODIFIER_CHOICES, True)
    c("the default costs the keyboard nothing",
      cross.stolen_characters(cross.MODIFIER_CHOICES[cross.DEFAULT_MODIFIER]), [])

    # The reason removing the name matters: a config written before the removal is
    # repaired on load, so nobody has to know about the Shortcuts tab to get their
    # keyboard back. The rest of the file must survive that repair untouched.
    repaired = load({"modifier": "Ctrl+Alt", "preset": 3, "monitor": 1})
    c("a config still holding Ctrl+Alt is repaired", repaired["modifier"],
      cross.DEFAULT_MODIFIER)
    c("the repair leaves the preset alone", repaired["preset"], 3)
    c("the repair leaves the screen alone", repaired["monitor"], 1)

    # The screen cap is the other half of load_config()'s contract, and it only
    # applies when the caller says how many screens exist: the app knows, a test
    # that forgets leaves the clamp unexercised.
    c("an out-of-range screen is capped when the count is known",
      write_config(cross, {"monitor": 99}, 2)["monitor"], 1)
    c("a negative screen is floored either way",
      write_config(cross, {"monitor": -5})["monitor"], 0)
    # Control: with no count, the upper cap must NOT fire. If this starts returning
    # a capped value, load_config() has begun guessing at the screen count.
    c("control: without the count the upper cap does not fire",
      write_config(cross, {"monitor": 99})["monitor"], 99)

    # Control: a modifier that is still on the menu must NOT be rewritten, or the
    # repair above is just load_config() flattening everything to the default.
    c("control: a saved Alt+Shift is KEPT", modifier({"modifier": "Alt+Shift"}),
      "Alt+Shift")
    c("control: a saved Ctrl+Alt+Shift is KEPT",
      modifier({"modifier": "Ctrl+Alt+Shift"}), "Ctrl+Alt+Shift")
    os.remove(cross.CONFIG_FILE)

    return c.finish()


run(main)
