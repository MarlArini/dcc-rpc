"""
AI-generated (Claude Opus 4.7): pytest configuration for the Painter test
subdirectory.

Path setup, in order:
  1. tests/painter/        — so `import substance_painter` finds the fake
                              instead of the real Adobe module.
  2. substance_painter_presence/ — so `from substance_painter_presence.painter_presence
                              import SPContext` works without a package install.
  3. repo root              — already added by the root conftest, but we ensure
                              order so the fake takes precedence.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_PAINTER_SOURCE = _REPO / "substance_painter_presence"

for path in (_REPO, _PAINTER_SOURCE, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _reset_painter_fake_state():
    """Reset the fake substance_painter module state before each test so
    test order doesn't matter."""
    import substance_painter
    substance_painter.reset_state()
    yield
    substance_painter.reset_state()


@pytest.fixture
def sp():
    """Direct access to the fake substance_painter module."""
    import substance_painter
    return substance_painter


@pytest.fixture(autouse=True, scope="session")
def _cleanup_painter_settings_json():
    """Importing painter_presence triggers SP_PLUGIN = SPPlugin(), whose
    JSONSharedSettings.setup_persistence writes painter_presence_settings.json
    into the plug-in directory. That's the right behavior at runtime but
    leaves a tracked-looking file in the source tree after the test session.
    Remove it once when the suite ends."""
    yield
    settings_file = _PAINTER_SOURCE / "painter_presence_settings.json"
    if settings_file.exists():
        try:
            settings_file.unlink()
        except OSError:
            pass
