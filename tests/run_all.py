"""Run every battery, and report which ones failed.

    py tests\\run_all.py

Windows only, and needs a desktop session: two of the three batteries open real
windows. They land on the second screen when there is one.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BATTERIES = ("test_modifier.py", "test_clickthrough.py", "test_window.py")


def main():
    failed = []
    for name in BATTERIES:
        print("=" * 70)
        print("  %s" % name)
        print("=" * 70)
        # without the flush, our own headers sit in the buffer behind the child's
        # output and the report reads out of order
        sys.stdout.flush()
        result = subprocess.run([sys.executable, os.path.join(HERE, name)], cwd=HERE)
        if result.returncode:
            failed.append(name)
        print()

    print("=" * 70)
    if failed:
        print("  %d of %d batteries FAILED: %s"
              % (len(failed), len(BATTERIES), ", ".join(failed)))
    else:
        print("  all %d batteries green" % len(BATTERIES))
    print("=" * 70)
    return 1 if failed else 0


sys.exit(main())
