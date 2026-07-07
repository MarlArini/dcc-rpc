"""
AI-generated (Claude Opus 4.7): pytest configuration for the Nuke tests.

The Nuke plugin (nuke_presence/menu.py) does heavy module-level work on
import: instantiates NK_PREFS, NK_MENU, NK_WORKER (background thread),
NK_RPC_CLIENT, and installs render callbacks. We can't avoid those running,
so we set up the fake to make them all succeed without side effects:

  - nuke.menu(...) returns a stub menu tree that records additions.
  - nuke.addBeforeRender/etc. record callbacks instead of firing anything.
  - NK_WORKER starts a daemon thread that waits NK_PREFS.generalUpdate
    seconds (15s default) between ticks; tests finish long before then.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_NUKE_SOURCE = _REPO / "nuke_presence"

for path in (_REPO, _NUKE_SOURCE, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _reset_nuke_fake_state():
    import nuke
    nuke.reset_state()
    yield
    nuke.reset_state()


@pytest.fixture
def nk():
    import nuke
    return nuke
