"""
AI-generated (Claude Opus 4.7): fake `maya.app.general.mayaMixin`.

Real MayaQWidgetDockableMixin is a multiple-inheritance helper that makes a
QWidget dockable inside Maya. For tests we only need a class that can sit in
the MRO without breaking — no docking behavior required.
"""
from __future__ import annotations


class MayaQWidgetDockableMixin:
    """Inert stand-in. The plugin uses this in
    `class MayaPresenceSettings(MayaQWidgetDockableMixin, QtSettingsGUIMenu)`;
    we just need the name to exist."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
