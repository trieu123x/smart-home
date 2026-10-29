"""Compatibility entry point for the new Windows venv + Docker dashboard setup."""
import os
from pathlib import Path
import subprocess


def main() -> int:
    if os.name != "nt":
        raise SystemExit("This launcher requires Windows. See docs/HYBRID_WINDOWS.md.")
    launcher = Path(__file__).resolve().parent / "START_SMART_HOME.bat"
    return subprocess.call(["cmd", "/c", str(launcher)], cwd=launcher.parent)


if __name__ == "__main__":
    raise SystemExit(main())
