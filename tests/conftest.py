"""
AI-generated (Claude Opus 4.7): root pytest configuration.

Adds the repo root to sys.path so every `from common import ...` and
`from colors import ...` resolves to the in-tree package regardless of which
test subdirectory pytest is invoked from. Per-plugin conftest.py files layer
additional paths (fake host modules, plugin source dirs) on top of this.

Provides a session-scoped QApplication so plugin modules that instantiate
QTimer at import time (every plugin going through RPCBasePlugin) can do so
without crashing under pytest.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    """A single QApplication for the test session.

    QTimer (and any QObject parented to the app) needs this to exist before
    construction; without it, plugin module imports can warn or crash.
    """
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app
    # Do not call app.quit() — tearing down the QApplication mid-test session
    # has caused intermittent failures on Windows in the past, and pytest
    # exits cleanly without it.
