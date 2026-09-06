"""Load Brady protocol modules without importing Home Assistant."""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "custom_components" / "brady_m211"

if "brady_m211" not in sys.modules:
    pkg = types.ModuleType("brady_m211")
    pkg.__path__ = [str(PKG_DIR)]
    pkg.__file__ = str(PKG_DIR / "__init__.py")
    pkg.__package__ = "brady_m211"
    sys.modules["brady_m211"] = pkg
