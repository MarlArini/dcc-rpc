"""
AI-generated (Claude Opus 4.7): pytest configuration for the Maya tests.

The Maya plugin loads with `import maya.cmds as cmds` and `import maya.api.
OpenMaya as om`. Both of those map onto the fake tree under tests/maya/maya/.

Maya's plugin is module-level (MP_PREFS / MP_SESSION / MP_UPDATE_DETAILS /
MP_RPC_CLIENT). MP_PREFS = MPSettings() runs MPSettings.__post_init__ which
iterates fields and calls cmds.optionVar(exists=ov) for each — so the fake
needs optionVar to be importable and callable.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_MAYA_SOURCE = _REPO / "maya_presence" / "plug-ins"

for path in (_REPO, _MAYA_SOURCE, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _reset_maya_fake_state():
    import maya.cmds as cmds
    cmds.reset_state()
    yield
    cmds.reset_state()


@pytest.fixture
def cmds():
    import maya.cmds as cmds
    return cmds
