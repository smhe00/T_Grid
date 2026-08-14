"""Unit tests for TGrid."""

import os
import sys

# Belt-and-braces: ensure src/ is importable even when discovery treats this
# directory (rather than tests/) as the top-level package.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
