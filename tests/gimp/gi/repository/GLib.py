"""AI-generated (Claude Opus 4.7): fake `gi.repository.GLib`.

Provides MainLoop + timeout_add / source_remove for gp_start_timer /
gp_stop_timer. The timer doesn't actually fire — tests invoke gp_tick
directly when they want to exercise the update path.
"""
from __future__ import annotations
from typing import Callable, Dict, Optional


class MainLoop:
    """Stand-in. tests don't call .run() — that would block."""

    def __init__(self):
        self._running = False
        self._quit_called = False

    def run(self) -> None:
        self._running = True

    def quit(self) -> None:
        self._quit_called = True
        self._running = False


# timeout bookkeeping — exposed so tests can assert on what got scheduled
_timeouts: Dict[int, Callable] = {}
_next_timeout_id: int = 0
_last_interval: Optional[int] = None


def timeout_add(interval: int, callback: Callable) -> int:
    global _next_timeout_id, _last_interval
    _next_timeout_id += 1
    _timeouts[_next_timeout_id] = callback
    _last_interval = interval
    return _next_timeout_id


def source_remove(source_id: int) -> bool:
    return _timeouts.pop(source_id, None) is not None


# Test helpers (not part of the real GLib API)
def _active_timeouts() -> Dict[int, Callable]:
    return dict(_timeouts)


def _last_scheduled_interval() -> Optional[int]:
    return _last_interval


def _reset_timeouts() -> None:
    global _next_timeout_id, _last_interval
    _timeouts.clear()
    _next_timeout_id = 0
    _last_interval = None
