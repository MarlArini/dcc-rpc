"""
AI-generated (Claude Opus 4.7): fake `nukescripts` package for tests.

Provides `panels` and `PythonPanel`. The plugin imports both at module load
but only uses panels.registerWidgetAsPanel inside a settings-window function
that tests don't exercise.
"""
from __future__ import annotations
from typing import Any


class PythonPanel:
    """Stand-in base class for nukescripts.PythonPanel."""

    def __init__(self, *args: Any, **kwargs: Any):
        pass

    def addToPane(self, pane: Any) -> None:  # noqa: N802
        pass


class _Panels:
    def registerWidgetAsPanel(self, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        return PythonPanel


panels = _Panels()
