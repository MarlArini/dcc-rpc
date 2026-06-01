"""
AI-generated (Claude Opus 4.7): pytest configuration for the C4D tests.

The C4D plugin source lives at c4d_presence/c4d_presence.pyp (a `.pyp`
file — Cinema 4D's plugin extension, but plain Python under the hood).
Importing it triggers module-level setup: C4DP_PREFS / C4DP_SESSION /
C4DP_UPDATE_DETAILS / C4DP_CLIENT instantiation and the registration
calls under `if __name__ == "__main__":` (skipped here because we import
as a regular module).

We put tests/c4d on sys.path so `import c4d` resolves to the fake,
and the repo root so `from common import ...` and
`from pypresence.presence import ...` resolve. The .pyp itself is
loaded via SourceFileLoader since importlib doesn't recognize .pyp.
"""
from __future__ import annotations
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_C4D_PLUGIN_DIR = _REPO / "c4d_presence"

# The dev .pyp does `from common import ...` and `from pypresence.presence
# import Presence` — bare absolute imports. Putting the repo root on
# sys.path makes both resolve (common/ and pypresence/ from site-packages).
for path in (_REPO, _C4D_PLUGIN_DIR, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


def _load_c4d_presence():
    """Load c4d_presence.pyp as a module named `c4d_presence`. importlib
    doesn't recognize .pyp as a source-file extension, so we go through
    SourceFileLoader explicitly."""
    if "c4d_presence" in sys.modules:
        return sys.modules["c4d_presence"]
    pyp_path = _C4D_PLUGIN_DIR / "c4d_presence.pyp"
    loader = importlib.machinery.SourceFileLoader("c4d_presence", str(pyp_path))
    spec = importlib.util.spec_from_loader("c4d_presence", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["c4d_presence"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _reset_c4d_fake_state():
    import c4d
    c4d.reset_state()
    yield
    c4d.reset_state()


@pytest.fixture
def c4d_mod():
    """The fake `c4d` module."""
    import c4d
    return c4d


@pytest.fixture
def c4dp():
    """The c4d_presence plugin module, loaded once."""
    return _load_c4d_presence()
