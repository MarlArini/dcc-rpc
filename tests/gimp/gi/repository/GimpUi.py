"""AI-generated (Claude Opus 4.7): fake `gi.repository.GimpUi`.

The settings dialog uses ProcedureDialog.new(...).run() — we never exercise
that path in tests (Gtk widget tree), so we provide just enough surface
to make import succeed.
"""
from __future__ import annotations
from typing import Any


def init(binary_name: str) -> None:
    """No-op; real GimpUi.init wires up GTK theming."""
    return None


class _ProcedureDialog:
    @staticmethod
    def new(procedure: Any, config: Any, title: str) -> "_ProcedureDialogInstance":
        return _ProcedureDialogInstance(procedure, config, title)


class _ProcedureDialogInstance:
    def __init__(self, procedure, config, title):
        self.procedure = procedure
        self.config = config
        self.title = title
        self.fill_calls = []
        self.fill_frame_calls = []
        self.fill_box_calls = []

    def fill(self, ids):
        self.fill_calls.append(list(ids))

    def fill_frame(self, frame_id, title_id, invert, children):
        self.fill_frame_calls.append((frame_id, title_id, invert, list(children)))

    def fill_box(self, box_id, children):
        self.fill_box_calls.append((box_id, list(children)))

        class _Box:
            def set_orientation(self_inner, orient):
                pass
        return _Box()

    def run(self):
        return True

    def destroy(self):
        pass


ProcedureDialog = _ProcedureDialog
