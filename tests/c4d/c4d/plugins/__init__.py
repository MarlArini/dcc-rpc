"""
AI-generated (Claude Opus 4.7): fake `c4d.plugins` submodule.

PreferenceData / MessageData are bare base classes — the plugin subclasses
them. RegisterPreferencePlugin / RegisterMessagePlugin record their kwargs
into module-level state so tests can assert that the plugin's __main__
block ran with the expected arguments.

PreferenceData.InitPreferenceValue is the one method the plugin actively
calls during description initialization; the fake implementation writes
the default value into the BaseContainer if no value is set yet.
"""
from __future__ import annotations
from typing import Any, Optional

from .. import (
    BaseContainer,
    DescID,
    DTYPE_BOOL,
    DTYPE_LONG,
    DTYPE_STRING,
    get_state,
)


class PreferenceData:
    """Base class for preference plugins. Subclasses override Init,
    GetDDescription, SetDParameter, GetDParameter, GetDEnabling, Message."""

    def InitPreferenceValue(  # noqa: N802
        self,
        param_id: int,
        default_value: Any,
        description: Any,
        desc_id: DescID,
        bc: BaseContainer,
    ) -> bool:
        """Mirrors C4D's real semantics: only write the default into the
        container if the slot is empty. We dispatch by the desc_id's dtype
        to match the slot type the plugin set up."""
        if desc_id is None:
            return False
        level = desc_id[0]
        dtype = level.dtype
        pid = int(param_id)
        if dtype == DTYPE_BOOL:
            if pid not in bc._bools:
                bc.SetBool(pid, bool(default_value))
        elif dtype == DTYPE_LONG:
            if pid not in bc._ints:
                bc.SetInt32(pid, int(default_value))
        elif dtype == DTYPE_STRING:
            if pid not in bc._strings:
                bc.SetString(pid, str(default_value))
        return True


class MessageData:
    """Base class for message plugins. Subclasses override GetTimer and
    CoreMessage."""
    pass


def RegisterPreferencePlugin(  # noqa: N802
    id: int,  # noqa: A002
    g: type,
    name: str,
    description: str,
    parentid: int = 0,
    sortid: int = 0,
    **kwargs,
) -> bool:
    get_state().registered_pref_plugins.append({
        "id": id, "g": g, "name": name, "description": description,
        "parentid": parentid, "sortid": sortid, **kwargs,
    })
    return True


def RegisterMessagePlugin(  # noqa: N802
    id: int,  # noqa: A002
    str: Optional[str] = None,  # noqa: A002
    info: int = 0,
    dat: Optional[MessageData] = None,
    **kwargs,
) -> bool:
    get_state().registered_msg_plugins.append({
        "id": id, "str": str, "info": info, "dat": dat, **kwargs,
    })
    return True
