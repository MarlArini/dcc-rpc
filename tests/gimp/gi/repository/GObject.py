"""AI-generated (Claude Opus 4.7): fake `gi.repository.GObject`.

settings_dialog uses GObject.ParamFlags.READWRITE as a flag value when
registering procedure arguments. We just need the constant to exist.
"""
from __future__ import annotations
import enum


class ParamFlags(enum.IntFlag):
    READABLE = 1
    WRITABLE = 2
    READWRITE = READABLE | WRITABLE
