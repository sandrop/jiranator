"""Test-time bootstrap for the jiranator plugin.

Puts the plugin's lib/ dir on sys.path so `import config` resolves in every
test under this tree, and the cli/ dir so `import jiranator` resolves
regardless of collection order. Mirrors the ccu plugin's bootstrap so
./run_tests.sh discovers this suite the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

_CLI = Path(__file__).resolve().parent / "cli"
if str(_CLI) not in sys.path:
    sys.path.insert(0, str(_CLI))
