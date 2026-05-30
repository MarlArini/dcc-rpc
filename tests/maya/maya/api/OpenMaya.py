"""
AI-generated (Claude Opus 4.7): fake `maya.api.OpenMaya`.

Provides MSceneMessage, MMessage, MTimerMessage, MFnPlugin — enough to make
mp_add_callbacks() and mp_schedule() succeed at module import. Callbacks
are recorded but never fired (tests of callbacks aren't in scope).
"""
from __future__ import annotations
from typing import Any, Callable, List, Tuple


_callback_id_counter = 0
_active_callbacks: List[Tuple[int, str, Callable]] = []


def _next_id() -> int:
    global _callback_id_counter
    _callback_id_counter += 1
    return _callback_id_counter


class MSceneMessage:
    kBeforeSave = "kBeforeSave"
    kAfterSave = "kAfterSave"
    kAfterNew = "kAfterNew"
    kAfterOpen = "kAfterOpen"
    kAfterPluginLoad = "kAfterPluginLoad"
    kAfterPluginUnload = "kAfterPluginUnload"

    @staticmethod
    def addCallback(event: str, fn: Callable) -> int:  # noqa: N802
        cid = _next_id()
        _active_callbacks.append((cid, event, fn))
        return cid

    @staticmethod
    def addStringArrayCallback(event: str, fn: Callable) -> int:  # noqa: N802
        cid = _next_id()
        _active_callbacks.append((cid, event, fn))
        return cid


class MMessage:
    @staticmethod
    def removeCallback(cid: int) -> None:  # noqa: N802
        global _active_callbacks
        _active_callbacks = [c for c in _active_callbacks if c[0] != cid]


class MTimerMessage:
    @staticmethod
    def addTimerCallback(period: float, fn: Callable) -> int:  # noqa: N802
        return _next_id()


class MFnPlugin:
    def __init__(self, mobject: Any, vendor: str = "", version: str = "", api_version: str = ""):
        self.mobject = mobject
        self.vendor = vendor
        self.version = version
        self.api_version = api_version
