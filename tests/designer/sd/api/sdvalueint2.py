"""AI-generated: fake `sd.api.sdvalueint2`."""
from __future__ import annotations
from dataclasses import dataclass, field
from .sdbasetypes import int2

@dataclass
class SDValueInt2:
    _value: int2 = field(default_factory=int2)

    def get(self) -> int2:
        return self._value
