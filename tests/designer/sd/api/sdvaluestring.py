"""AI-generated (Claude Opus 4.7): fake `sd.api.sdvaluestring`."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class SDValueString:
    _value: str = ""

    def get(self) -> str:
        return self._value
