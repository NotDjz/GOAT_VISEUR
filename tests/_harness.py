"""Shared scaffolding: load the app from a throwaway copy, and report results.

`CONFIG_FILE` is derived from the module's own location, so importing the repo's
`crosshair.pyw` directly makes every write land on the developer's live
`config.json` — which is how ten hand-made presets were once destroyed by a test
that only meant to reproduce a display bug. Every battery therefore goes through
`load_module()`, and the assertion at the end of it is the guard that keeps that
from happening again.
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module():
    """Copy crosshair.pyw (and the icon) somewhere disposable, then import it."""
    work = tempfile.mkdtemp(prefix="screenscope-test-")
    shutil.copy(os.path.join(REPO, "crosshair.pyw"), work)
    icon = os.path.join(REPO, "screenscope.ico")
    if os.path.exists(icon):
        shutil.copy(icon, work)

    spec = importlib.util.spec_from_file_location(
        "crosshair_under_test", os.path.join(work, "crosshair.pyw"))
    if spec is None or spec.loader is None:
        raise AssertionError("could not build an import spec for the copy in %r" % work)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if os.path.dirname(module.CONFIG_FILE) != work:
        raise AssertionError(
            "the module escaped its copy: CONFIG_FILE is %r, expected it under %r"
            % (module.CONFIG_FILE, work))
    return module


def write_config(module, payload, monitor_count=None):
    """Write a config next to the copy, and load it back the way the app would.

    `monitor_count` is passed through because only a caller that knows how many
    screens exist lets `load_config()` cap `monitor` from above; a battery that
    omits it leaves that clamp untested.
    """
    with io.open(module.CONFIG_FILE, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
    return module.load_config(monitor_count)


def test_screen(monitors):
    """The second screen when there is one — never the primary."""
    return 1 if len(monitors) > 1 else 0


class Checks:
    """Counts failures so a battery can exit non-zero without raising."""

    def __init__(self, title):
        self.failed = []
        print(title)

    def __call__(self, name, got, want):
        ok = got == want
        print("  %-58s %s" % (name, "OK" if ok else "FAIL"))
        if not ok:
            print("      expected %r" % (want,))
            print("      got      %r" % (got,))
            self.failed.append(name)
        return ok

    def note(self, text):
        print("      %s" % text)

    def section(self, title):
        print()
        print(title)

    def finish(self):
        print()
        if self.failed:
            print("RESULT: %d FAILED: %s" % (len(self.failed), ", ".join(self.failed)))
        else:
            print("RESULT: ALL GREEN")
        return 1 if self.failed else 0


def run(main):
    sys.exit(main())
