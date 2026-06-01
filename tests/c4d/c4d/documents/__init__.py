"""
AI-generated (Claude Opus 4.7): fake `c4d.documents` submodule.

Re-exports BaseDocument from the parent c4d module and provides
GetActiveDocument() which reads from the parent's module-level state.
"""
from __future__ import annotations
from typing import Optional

from .. import BaseDocument, get_state  # noqa: F401


def GetActiveDocument() -> Optional[BaseDocument]:  # noqa: N802
    return get_state().active_doc
