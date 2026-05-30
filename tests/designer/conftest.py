"""
AI-generated (Claude Opus 4.7): pytest configuration for the Designer tests.

Designer's plugin lives at substance_designer_presence/designerpresence/
designerpresence/__init__.py and imports as `designerpresence`. To resolve
that we put the outer designerpresence/ on sys.path.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_DESIGNER_PACKAGE_PARENT = (
    _REPO / "substance_designer_presence" / "designerpresence"
)

for path in (_REPO, _DESIGNER_PACKAGE_PARENT, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _reset_sd_fake_state():
    import sd
    sd.reset_state()
    yield
    sd.reset_state()


@pytest.fixture
def sd():
    import sd
    return sd
