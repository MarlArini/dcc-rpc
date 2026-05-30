"""
AI-generated (Claude Opus 4.7): pytest configuration for the Krita tests.

Path setup:
  1. tests/krita/                — for `import krita` (the fake).
  2. krita_presence/krita_presence/  — for `from krita_presence ...`.
  3. repo root                   — for `from common ...` and `from colors ...`.

PyQt5 aliasing:
  Krita uses PyQt5 but our dev environment has PySide6 (krita_presence ships
  inside Krita's own bundled PyQt5). We install sys.modules aliases so the
  plugin's `import PyQt5.QtCore as qc` etc. resolves to PySide6's modules.
  This works because the two APIs are 99% identical for what krita_presence
  uses (QObject, QApplication, QEvent, QColor, etc.).
"""
from __future__ import annotations
import sys
import types
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_KRITA_SOURCE = _REPO / "krita_presence" / "krita_presence"

for path in (_REPO, _KRITA_SOURCE, _HERE):
    p = str(path)
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)


# Install PyQt5 → PySide6 aliases BEFORE the plugin module is imported. Top of
# this file is the right place because pytest imports conftest before any test
# file, so the aliases exist by the time anything reaches `import PyQt5...`.
def _alias_pyqt5_to_pyside6():
    from PySide6 import QtCore, QtGui, QtWidgets
    pyqt5 = types.ModuleType("PyQt5")
    pyqt5.QtCore = QtCore
    pyqt5.QtGui = QtGui
    pyqt5.QtWidgets = QtWidgets
    sys.modules.setdefault("PyQt5", pyqt5)
    sys.modules.setdefault("PyQt5.QtCore", QtCore)
    sys.modules.setdefault("PyQt5.QtGui", QtGui)
    sys.modules.setdefault("PyQt5.QtWidgets", QtWidgets)


_alias_pyqt5_to_pyside6()


@pytest.fixture(autouse=True)
def _reset_krita_fake_state():
    import krita
    krita.reset_state()
    yield
    krita.reset_state()


@pytest.fixture
def kr():
    import krita
    return krita
