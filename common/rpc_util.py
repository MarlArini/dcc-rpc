"""RPC-specific functionality shared by most or all plugins"""

import time
from typing import Dict, Callable
from pypresence.presence import Presence
from pypresence import exceptions

from .util_classes import SharedSettings, SessionInfo, RPCUpdateDetails
from .util import is_url, pad_text

# For long sessions the Discord RPC update rate limit is ~15 seconds, but
# for users adjusting the settings menu, a short term event, it should be
# possible to send another update even if only 10 seconds have elapsed
DISCORD_SHORT_TERM_RATE_LIMIT = 10


def rpc_update(details: RPCUpdateDetails, client: Presence, enable_time: bool):
    """Send an update to the RPC client. May raise exceptions which must be handled."""
    client.update(
        start=details.start_time if enable_time else None,
        state=details.state_text if details.state_text else None,
        details=details.details_text if details.details_text else "  ",
        small_image=details.small_icon,
        small_text=details.small_icon_text if details.small_icon_text else None,
        large_image=details.large_icon,
        large_text=details.large_icon_text if details.large_icon_text else None,
        buttons=details.buttons if details.buttons else None,
    )


def force_clear_on_exit(client: Presence):
    """Method to try to close the RPC client; register with atexit for situations where
    the normal routes fail to close the client during application shutdown"""
    try:
        client.clear()
        client.close()
    except BaseException:
        pass


def update_buttons(details: RPCUpdateDetails, prefs: SharedSettings):
    """Check validity of user buttons, if enabled, and update the RPC details."""
    details.buttons = []
    if is_url(prefs.button1Url) and prefs.button1Label and prefs.enableButton1:
        details.buttons.append({"label": prefs.button1Label, "url": prefs.button1Url})
    if is_url(prefs.button2Url) and prefs.button2Label and prefs.enableButton2:
        details.buttons.append({"label": prefs.button2Label, "url": prefs.button2Url})


def connect_rpc(client: Presence, app_name: str, error: Callable = print):
    try:
        client.connect()
        return True
    except Exception as e:
        error(f"[{app_name.title()}Presence] Connection Error: {e}")
        return False


def push_rpc_update(
    session: SessionInfo,
    details: RPCUpdateDetails,
    prefs: SharedSettings,
    client: Presence,
    app_name: str,
    error: Callable = print,
):
    """Try to push an RPC update. If the session is not connected, the
    function attempts to connect and tries another push if the connection
    succeeds. If the session is connected but the update still fails, the
    connection is set to False, a new connection attempt is made, and the
    function returns without attempting another update."""
    success = False
    if session.connected:
        try:
            rpc_update(details, client, prefs.enableTime)
            success = True
        except (
            exceptions.InvalidID,
            AssertionError,
            exceptions.PipeClosed,
            exceptions.DiscordNotFound,
            exceptions.ServerError,
        ) as e:
            session.connected = False
            error(f"[{app_name.title()}Presence] RPC Connection Lost: {e}")
            session.connected = connect_rpc(client, app_name, error)
    else:
        error(f"[{app_name.title()}Presence] Retrying...")
        session.connected = connect_rpc(client, app_name, error)
        if session.connected:
            push_rpc_update(session, details, prefs, client, app_name, error)
    if success:
        session.last_update = time.time()
        session.cleared = False


def advance_cycle(session: SessionInfo, display_types: Dict):
    session.cycle_iter = (session.cycle_iter + 1) % len(display_types)


_SLOT_PEER = {"state": "details", "details": "state"}
_SLOT_OFFSET = {"state": 0, "details": 1}


def update_slot(
    ctx,
    slot: str,
    prefs: SharedSettings,
    details: RPCUpdateDetails,
    display_types: Dict[str, Callable],
    session: SessionInfo,
) -> None:
    """Update the details or state slots of the RPCUpdateDetails object for
    this RPC update. Checks the prefs to see if the slot is enabled."""
    peer = _SLOT_PEER[slot]
    text_attr = f"{slot}_text"
    setattr(details, text_attr, "")

    if not getattr(prefs, f"enable{slot.capitalize()}"):
        return
    custom = getattr(prefs, f"custom{slot.capitalize()}")
    if custom:
        setattr(details, text_attr, pad_text(custom))
        return

    cycling = getattr(prefs, f"{slot}Cycle")
    peer_cycling = getattr(prefs, f"{peer}Cycle")
    peer_fixed = getattr(prefs, f"{peer}Type")
    fixed = getattr(prefs, f"{slot}Type")

    if cycling:
        text = pick_cycling(
            ctx, peer_cycling, peer_fixed, _SLOT_OFFSET[slot], display_types, session
        )
    else:
        text = pick_fixed(ctx, fixed, display_types)

    text = pad_text(text)
    setattr(details, text_attr, text)


def pick_fixed(ctx, kind: str, display_types: Dict[str, Callable]) -> str:
    """Get the value for a slot locked to a fixed display type"""
    fn = display_types.get(kind)
    if fn is None:
        return ""
    value = fn(ctx)
    return str(value) if value not in (None, "") else ""


def pick_cycling(
    ctx,
    peer_cycling: bool,
    peer_fixed: str,
    offset: int,
    display_types: Dict[str, Callable],
    session: SessionInfo,
) -> str:
    """Get the value for a slot with a cycling display type. Skips the type its
    peer is on if the peer is fixed, and skips None results."""
    display_cycle = list(display_types)
    n = len(display_cycle)
    start = (session.cycle_iter + offset) % n
    # Skip the slot occupied by a fixed peer.
    if not peer_cycling:
        skip = peer_fixed
    else:
        skip = None
    for i in range(n):
        idx = (start + i) % n
        kind = display_cycle[idx]
        if kind == skip:
            continue
        value = display_types[kind](ctx)
        if value not in (None, ""):
            return str(value)
    return ""  # nothing meaningful in the entire cycle
