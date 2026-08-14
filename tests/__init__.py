"""Test package for TGrid.

Ensures the ``src/`` directory is importable regardless of how ``unittest``
discovery is invoked (the project uses a src-layout).
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
