"""Capturing a modifier combination from the keyboard.

Two halves, deliberately separate.

The state machine is driven with a stubbed `held_modifiers()`, so it needs no real
keystrokes: it checks that the widest set held wins, that a single modifier is
refused, and that Escape and the timeout both leave the setting untouched.

`held_modifiers()` itself is the half that must touch the real keyboard, because
the whole reason it exists is that tk never sees Alt or Win. It synthesizes keys
with `keybd_event`, which is **disruptive**: those keystrokes go to whatever has
focus. Do not run this file while a game is in the foreground.

Never use Alt+Shift in that half. It is Windows' default language-switch shortcut,
and a probe that used it silently flipped the developer's keyboard from French to
US in the middle of a measurement session.
"""
import ctypes
import os
import time

from _harness import Checks, load_module, open_settings, run

user32 = ctypes.windll.user32


def main():
    cross = load_module()
    root, settings, config = open_settings(cross)
    settings._show_tab("shortcuts")
    root.update_idletasks()

    # Both halves read the virtual keys and the flags off the module's own table,
    # rather than restating them and letting the two drift apart.
    vk_of = {name: keys[0] for name, _bit, keys in cross.MODIFIER_PARTS}
    bit_of = cross.MODIFIER_BITS

    c = Checks("BATTERY 8 - the capture state machine")
    c.note("driven with a stubbed keyboard, no real keystrokes")

    def step():
        """Run one tick of the loop by hand, without waiting for the scheduler."""
        if settings._capture_after is None:
            return False
        # on the window that scheduled it: cancelling from another widget deletes
        # the Tcl command out of the wrong bookkeeping, and that window's later
        # destroy() then fails on a name it still thinks it owns.
        settings.win.after_cancel(settings._capture_after)
        settings._capture_after = None
        settings._poll_capture()
        return True

    def drive(sequence, previous="Ctrl+Shift"):
        """Run the loop over a scripted sequence of held-modifier readings.

        Always leaves the capture stopped. A sequence that never commits (all
        zeros) otherwise leaves the loop scheduled, and the next call's
        `_toggle_capture()` cancels it instead of starting one, so the check after
        it would pass without reading the keyboard at all.
        """
        assert settings._capture_after is None, "a capture was left running"
        config["modifier"] = previous
        real = cross.held_modifiers
        steps = list(sequence)
        reads = []

        def stub():
            value = steps.pop(0) if steps else 0
            reads.append(value)
            return value

        cross.held_modifiers = stub
        try:
            settings._toggle_capture()
            for _ in range(len(sequence) + 2):
                if not step():
                    break
            if settings._capture_after is not None:
                settings._end_capture(0)
        finally:
            cross.held_modifiers = real
        drive.reads = reads
        return config["modifier"]

    CTRL, ALT, SHIFT = cross.MOD_CONTROL, cross.MOD_ALT, cross.MOD_SHIFT

    c("a two-key combination is captured", drive([CTRL, CTRL | ALT, 0]), "Ctrl+Alt")
    # The widest set wins: releasing one key at a time must not capture whatever
    # happens to be left at the end.
    c("releasing one key at a time keeps the whole combination",
      drive([CTRL, CTRL | ALT | SHIFT, ALT | SHIFT, SHIFT, 0]), "Ctrl+Alt+Shift")
    c("a four-key combination is captured",
      drive([CTRL | ALT | SHIFT | cross.MOD_WIN, 0]), "Ctrl+Alt+Shift+Win")

    c.section("BATTERY 8b - control: what the capture must refuse")
    # Without these the checks above would pass on a machine that accepts anything.
    c("control: a single modifier is not captured", drive([CTRL, 0]), "Ctrl+Shift")
    c("control: nothing held changes nothing", drive([0, 0, 0]), "Ctrl+Shift")
    c("and it really did read the keyboard", bool(drive.reads), True)
    c("control: a refused capture leaves the previous value",
      drive([cross.MOD_WIN, 0], previous="Alt+Shift"), "Alt+Shift")
    c("and that one read the keyboard too", bool(drive.reads), True)

    c.section("BATTERY 8c - the timeout releases the tab")
    config["modifier"] = "Ctrl+Shift"
    settings._toggle_capture()
    settings._capture_ticks = settings.CAPTURE_TIMEOUT_MS // settings.CAPTURE_POLL_MS
    step()
    c("the loop stops on timeout", settings._capture_after, None)
    c("and the button goes back to Change", settings.capture_btn.cget("text"), "Change")
    c("and the modifier is untouched", config["modifier"], "Ctrl+Shift")

    c.section("BATTERY 9 - held_modifiers sees what tk cannot")
    # The reason this function exists: tk delivers neither Alt (a system key) nor
    # Win (swallowed by the shell), so an event-driven capture could not offer them.
    # Alt+Shift is deliberately absent from this list — it is Windows' language
    # switch, and sending it once flipped the developer's keyboard mid-session.
    def synthesize(names):
        vks = [vk_of[n] for n in names]
        for vk in vks:
            user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.08)
        got = cross.held_modifiers()
        for vk in reversed(vks):
            user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.12)
        return got

    for names in (("Ctrl", "Shift"), ("Ctrl", "Alt"), ("Ctrl", "Alt", "Shift"),
                  ("Win", "Shift")):
        want = 0
        for n in names:
            want |= bit_of[n]
        c("%-22s is seen" % "+".join(names),
          cross.modifier_name(synthesize(names)), cross.modifier_name(want))

    # Control: with nothing held it must report nothing, or every check above would
    # pass on a function that returns a constant.
    c("control: nothing held reports nothing", cross.held_modifiers(), 0)

    settings.win.destroy()
    root.destroy()
    os.remove(cross.CONFIG_FILE)
    return c.finish()


run(main)
