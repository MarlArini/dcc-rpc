"""
AI-generated (Claude Opus 4.7): pytest configuration for the GIMP tests.

Path setup:
  1. tests/gimp/        — for `import gi` (the fake)
  2. gimp_presence/     — for `from gimp_presence import ...` and the
                           `from settings_dialog import ...` sibling import
  3. repo root          — for `from common import ...` and `from colors import ...`

The GIMP plugin's module body ends with `Gimp.main(...)`. The fake's
`Gimp.main` is a no-op, so importing gimp_presence is safe in tests.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_GIMP_SOURCE = _REPO / "gimp_presence"

for path in (_REPO, _GIMP_SOURCE, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _reset_gimp_fake_state():
    """Reset fake Gimp module state between tests so order doesn't matter."""
    from gi.repository import Gimp
    Gimp.reset_state()
    yield
    Gimp.reset_state()


@pytest.fixture
def gimp():
    from gi.repository import Gimp
    return Gimp
