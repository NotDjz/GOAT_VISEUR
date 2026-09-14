"""Run every battery, and report which ones failed.

    py tests\\run_all.py

Windows only, and needs a desktop session: three of the four batteries open real
windows, on the second screen when there is one. `test_capture.py` also synthesizes
global keystrokes, so do not run the suite while a game is in the foreground.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BATTERIES = ("test_modifier.py", "test_capture.py", "test_clickthrough.py",
             "test_window.py")


def main():
    failed, skipped = [], []
    for name in BATTERIES:
        print("=" * 70)
        print("  %s" % name)
        print("=" * 70)
        # without the flush, our own headers sit in the buffer behind the child's
        # output and the report reads out of order
        sys.stdout.flush()
        result = subprocess.run([sys.executable, os.path.join(HERE, name)], cwd=HERE)
        if result.returncode == 1:
            failed.append(name)
        elif result.returncode == 2:
            skipped.append(name)
        print()

    print("=" * 70)
    if failed:
        print("  %d of %d batteries FAILED: %s"
              % (len(failed), len(BATTERIES), ", ".join(failed)))
    elif skipped:
        print("  all %d batteries green, but %s skipped a leg"
              % (len(BATTERIES), ", ".join(skipped)))
    else:
        print("  all %d batteries green" % len(BATTERIES))
    print("=" * 70)
    return 1 if failed else 0


sys.exit(main())
