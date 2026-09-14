"""The hotkey modifier: its format, the default, and what a combination costs.

The modifier is free: the user presses whichever combination of Ctrl, Alt, Shift
and Win they want, and the Shortcuts tab captures it. `modifier_flags()` is the
single reader of that format and the single place that decides what is usable, so
these batteries hammer it rather than any caller.

Two modifiers minimum is the one rule: a single one would turn Ctrl+S, Ctrl+Q and
Ctrl+1..0 into global grabs and take Save and Quit away from every other
application on the machine.
"""
import itertools
import os

from _harness import Checks, load_module, run, write_config


def main():
    cross = load_module()
    c = Checks("BATTERY 1 - the modifier format")

    parts = [name for name, _bit, _keys in cross.MODIFIER_PARTS]
    c.note("known parts: %s" % ", ".join(parts))

    # Round trip: every combination of two parts or more must survive being turned
    # into flags and back, in canonical order.
    combos = [combo for size in range(2, len(parts) + 1)
              for combo in itertools.combinations(parts, size)]
    bad = []
    for combo in combos:
        name = "+".join(combo)
        flags = cross.modifier_flags(name)
        if flags is None or cross.modifier_name(flags) != name:
            bad.append(name)
    c.note("%d combinations of 2 parts or more" % len(combos))
    c("every one survives the round trip", bad, [])

    # Order is canonical, so the same combination always spells the same way.
    c("a reversed spelling normalizes", cross.modifier_name(
        cross.modifier_flags("Shift+Ctrl")), "Ctrl+Shift")
    c("Win sorts last", cross.modifier_name(cross.modifier_flags("Win+Ctrl")),
      "Ctrl+Win")
    c("MOD_NOREPEAT is always set",
      bool(cross.modifier_flags("Ctrl+Shift") & cross.MOD_NOREPEAT), True)

    c.section("BATTERY 1b - control: what the format must refuse")
    # Without these the round trip above would pass on a function that accepts
    # anything, which is exactly the failure this control exists to catch.
    for value, why in (("Ctrl", "a single modifier"),
                       ("Win", "a single modifier"),
                       ("", "an empty string"),
                       ("Ctrl+Ctrl", "a repeated part"),
                       ("Ctrl+Meta", "an unknown part"),
                       ("Win+Z", "a key, not a modifier"),
                       (7, "a number"),
                       (None, "nothing at all"),
                       (["Ctrl", "Alt"], "a list")):
        c("control: %-24s is refused" % why, cross.modifier_flags(value), None)

    c.section("BATTERY 2 - the default, and what load_config normalizes")

    def load(payload, monitor_count=None):
        return write_config(cross, payload, monitor_count)

    def modifier(payload):
        return load(payload)["modifier"]

    c("the default parses", cross.modifier_flags(cross.DEFAULT_MODIFIER) is not None,
      True)
    c("no modifier key      -> the default", modifier({}), cross.DEFAULT_MODIFIER)
    c("a single modifier    -> the default", modifier({"modifier": "Ctrl"}),
      cross.DEFAULT_MODIFIER)
    c("unknown modifier     -> the default", modifier({"modifier": "Win+Z"}),
      cross.DEFAULT_MODIFIER)
    c("non-string modifier  -> the default", modifier({"modifier": 7}),
      cross.DEFAULT_MODIFIER)
    c("a hand-edited spelling is normalized", modifier({"modifier": "Shift+Ctrl"}),
      "Ctrl+Shift")

    # Ctrl+Alt is a usable combination again now that the choice is free. It costs
    # characters on an AltGr layout, which is what the Shortcuts tab warns about;
    # load_config() no longer second-guesses it.
    kept = load({"modifier": "Ctrl+Alt", "preset": 3, "monitor": 1})
    c("control: a saved Ctrl+Alt is KEPT, not overridden", kept["modifier"],
      "Ctrl+Alt")
    c("keeping it leaves the preset alone", kept["preset"], 3)
    c("keeping it leaves the screen alone", kept["monitor"], 1)
    for name in ("Alt+Shift", "Ctrl+Alt+Shift", "Ctrl+Win"):
        c("control: a saved %-14s is KEPT" % name, modifier({"modifier": name}), name)

    c.section("BATTERY 3 - what a combination costs the keyboard")
    # Layout-dependent, so the battery reports rather than asserting blind. On a
    # French AZERTY, Ctrl+Alt is AltGr and takes @ ~ # { [ | ` and \ away.
    layout = cross.user32.GetKeyboardLayout(0) & 0xFFFF
    stolen = cross.stolen_characters(cross.modifier_flags("Ctrl+Alt"))
    c.note("active layout 0x%04X, Ctrl+Alt takes: %s"
           % (layout, ", ".join("%s=%s" % kv for kv in stolen) or "nothing"))
    if layout == 0x040C:
        c("Ctrl+Alt takes the 8 AZERTY characters", dict(stolen),
          {"0": "@", "2": "~", "3": "#", "4": "{",
           "5": "[", "6": "|", "7": "`", "8": "\\"})
        # Control: the same query under a modifier with no AltGr level must come
        # back empty, or the function is reporting the layout rather than the combo.
        c("control: Ctrl+Shift takes nothing",
          cross.stolen_characters(cross.modifier_flags("Ctrl+Shift")), [])
    else:
        c.note("not a French layout: skipping the character assertions")
    c("every key named is one we register",
      all(ord(k) in cross.HOTKEY_DEFS.values() for k, _ in stolen), True)

    # Win is not a layout modifier: Windows never routes it into the keyboard
    # layout, so no character can require it and none can be stolen by it. Without
    # the guard, VkKeyScan's three state bits (no Win among them) make Shift+Win
    # measure as plain Shift and claim the 13 characters Shift produces.
    for name in ("Shift+Win", "Ctrl+Win", "Ctrl+Alt+Win", "Ctrl+Alt+Shift+Win"):
        c("%-20s costs nothing, Win is not a layout key" % name,
          cross.stolen_characters(cross.modifier_flags(name)), [])
    # Control: drop the Win bit and the same combination reports again, so the
    # check above is the guard working and not the scan failing on everything.
    c("control: the same combination without Win does report",
      bool(cross.stolen_characters(cross.modifier_flags("Ctrl+Alt"))),
      layout == 0x040C)

    c.section("BATTERY 4 - the screen and preset indices")
    c("an out-of-range screen is capped when the count is known",
      load({"monitor": 99}, 2)["monitor"], 1)
    c("a negative screen is floored either way", load({"monitor": -5})["monitor"], 0)
    c("control: without the count the upper cap does not fire",
      load({"monitor": 99})["monitor"], 99)
    c("an out-of-range preset is clamped", load({"preset": 99})["preset"], 9)
    c("a non-integer preset falls back to 0", load({"preset": "third"})["preset"], 0)
    c("control: a valid preset is left alone", load({"preset": 7})["preset"], 7)

    os.remove(cross.CONFIG_FILE)
    return c.finish()


run(main)
