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


def GetFirstDocument() -> Optional[BaseDocument]:  # noqa: N802
    """Head of the open-document list. Tests populate it with
    set_state(open_docs=[...]); it stays empty (returning None) otherwise,
    which the plugin reads as 'no answer' and leaves its memo alone."""
    docs = get_state().open_docs
    return docs[0] if docs else None
