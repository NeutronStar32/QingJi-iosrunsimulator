"""Rebuild the page without starting the server or contacting a phone."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qingji.assets import build_ui

if __name__ == "__main__":
    build_ui()
