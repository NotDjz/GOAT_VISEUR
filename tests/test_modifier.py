"""The hotkey modifier: what the default is, and how an old config is repaired.

Windows transmits AltGr as Ctrl+Alt, so registering Ctrl+Alt + a digit globally
took eight characters off a French AZERTY keyboard. `Ctrl+Alt` was removed from
`MODIFIER_CHOICES` outright, and that removal is what repairs existing files:
`load_config()` no longer recognises the name, so a config written before it falls
back to the default on load instead of going on stealing characters.

Battery 1 pins the menu itself; the rest cover `load_config()`'s contract for the
modifier and the two indices.
"""
import os

from _harness import Checks, load_module, run, write_config


def main():
    cross = load_module()
    c = Checks("BATTERY 1 - the offered modifiers")

    c("Ctrl+Alt is not offered", "Ctrl+Alt" in cross.MODIFIER_CHOICES, False)
    c("the default is one of the offered choices",
      cross.DEFAULT_MODIFIER in cross.MODIFIER_CHOICES, True)
    # The shape that matters: Ctrl+Alt with nothing else is what Windows sends for
    # AltGr. Naming it this way catches the combination coming back under any name.
    def ctrl_alt_alone(choices):
        return [n for n, f in choices.items()
                if f & cross.MOD_CONTROL and f & cross.MOD_ALT
                and not f & cross.MOD_SHIFT]

    c("no offered modifier is Ctrl+Alt alone", ctrl_alt_alone(cross.MODIFIER_CHOICES), [])
    # Control: the same predicate run against a menu that DOES hold the combination
    # must name it. Without this, a mis-written predicate passes on any dict.
    c("control: the same test names a Ctrl+Alt entry",
      ctrl_alt_alone({"AltGr": cross.MOD_CONTROL | cross.MOD_ALT | cross.MOD_NOREPEAT}),
      ["AltGr"])

    c.section("BATTERY 2 - the default, and the repair of older configs")

    def load(payload, monitor_count=None):
        return write_config(cross, payload, monitor_count)

    def modifier(payload):
        return load(payload)["modifier"]

    c("no modifier key      -> the default", modifier({}), cross.DEFAULT_MODIFIER)
    c("unknown modifier     -> the default", modifier({"modifier": "Win+Z"}),
      cross.DEFAULT_MODIFIER)
    c("non-string modifier  -> the default", modifier({"modifier": 7}),
      cross.DEFAULT_MODIFIER)

    # The reason removing the name matters: a config written before the removal is
    # repaired on load, so nobody has to know about the Shortcuts tab to get their
    # keyboard back. The rest of the file must survive that repair untouched.
    repaired = load({"modifier": "Ctrl+Alt", "preset": 3, "monitor": 1})
    c("a config still holding Ctrl+Alt is repaired", repaired["modifier"],
      cross.DEFAULT_MODIFIER)
    c("the repair leaves the preset alone", repaired["preset"], 3)
    c("the repair leaves the screen alone", repaired["monitor"], 1)

    # Control: a modifier that is still on the menu must NOT be rewritten, or the
    # repair above is just load_config() flattening everything to the default.
    for name in cross.MODIFIER_CHOICES:
        if name == cross.DEFAULT_MODIFIER:
            # would pass under the very failure it guards against, so it measures
            # nothing; the other names carry the check.
            continue
        c("control: a saved %s is KEPT" % name, modifier({"modifier": name}), name)

    c.section("BATTERY 3 - the screen index")
    # The upper cap only applies when the caller says how many screens exist: the
    # app knows, and a test that forgets leaves the clamp unexercised.
    c("an out-of-range screen is capped when the count is known",
      load({"monitor": 99}, 2)["monitor"], 1)
    c("a negative screen is floored either way", load({"monitor": -5})["monitor"], 0)
    # Control: with no count, the upper cap must NOT fire. If this starts returning
    # a capped value, load_config() has begun guessing at the screen count.
    c("control: without the count the upper cap does not fire",
      load({"monitor": 99})["monitor"], 99)

    c.section("BATTERY 4 - the preset index")
    c("an out-of-range preset is clamped", load({"preset": 99})["preset"], 9)
    c("a negative preset is clamped", load({"preset": -1})["preset"], 0)
    c("a non-integer preset falls back to 0", load({"preset": "third"})["preset"], 0)
    # Control: a valid preset must come back untouched, or the clamp is just
    # flattening every value to zero.
    c("control: a valid preset is left alone", load({"preset": 7})["preset"], 7)

    os.remove(cross.CONFIG_FILE)
    return c.finish()


run(main)
