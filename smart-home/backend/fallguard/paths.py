"""Asset paths for the integrated module; independent of the launch directory."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(os.environ.get('FALL_ASSETS_DIR', str(ROOT))).resolve()
