"""AI-generated (Claude Opus 4.7): fake `gi.repository.Gtk`.

The settings dialog references Gtk.Orientation.VERTICAL when configuring
fill_box layout. That's the only Gtk surface tests need.
"""
from __future__ import annotations
import enum


class Orientation(enum.Enum):
    HORIZONTAL = 0
    VERTICAL = 1
