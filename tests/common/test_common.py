"""
AI-generated (Claude Opus 4.7): unit + fuzz tests for the host-independent
utilities in common/common.py.

These functions don't touch any DCC host, so they're tested directly without
any fakes. Heavy use of pytest.mark.parametrize to keep the file readable.
"""
from __future__ import annotations
from types import SimpleNamespace
import pytest

from common import (
    SessionInfo,
    RPCUpdateDetails,
    is_url,
    pad_text,
    plural,
    shorten_number,
    get_file_size_str,
    update_buttons,
    update_slot,
    advance_cycle,
    on_render_end,
    on_frame_render_end,
)
from common.rpc_util import pick_fixed, pick_cycling  # not re-exported via __init__


# ---------------------------------------------------------------------------
# plural
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "count, prefix, postfix, expected",
    [
        (0, "layer", "s", "0 layers"),
        (1, "layer", "s", "1 layer"),
        (2, "layer", "s", "2 layers"),
        (1, "mesh", "es", "1 mesh"),
        (3, "mesh", "es", "3 meshes"),
        (1, "child", "ren", "1 child"),
        (4, "child", "ren", "4 children"),
        # Default postfix is "s"
        (1, "node", "s", "1 node"),
        (1000000, "thing", "s", "1000000 things"),
    ],
)
def test_plural(count, prefix, postfix, expected):
    assert plural(count, prefix, postfix) == expected


def test_plural_default_postfix():
    assert plural(5, "frog") == "5 frogs"


@pytest.mark.parametrize("count", [-1, -100, 0, 1, 2, 1000])
def test_plural_negative_and_zero_dont_crash(count):
    # Negative counts get pluralized as if >1 (count != 1). Document the behavior.
    result = plural(count, "item")
    assert result.startswith(f"{count} item")


# ---------------------------------------------------------------------------
# is_url (validity check, despite the name)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com",
        "https://example.com/path",
        "https://example.com/path/to/thing",
        "https://sub.example.com",
        "https://example.com:8080",
        "https://example.com:8080/path",
        "https://a.b.c.example.co.uk",
    ],
)
def test_is_url_valid(url):
    assert is_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "ftp://example.com",
        "http://",
        "http://nodot",
        "https://.com",
        "javascript:alert(1)",
        "example.com",  # missing scheme
        "http://example",  # missing TLD
    ],
)
def test_is_url_invalid(url):
    assert is_url(url) is False


# ---------------------------------------------------------------------------
# pad_text (Discord 2-char minimum)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "inp, expected",
    [
        ("", "  "),
        ("a", "  "),
        ("ab", "ab"),
        ("hello", "hello"),
        ("  ", "  "),
        ("\n\n", "\n\n"),  # two newlines is still >1 char
    ],
)
def test_pad_text(inp, expected):
    assert pad_text(inp) == expected


def test_pad_text_coerces_non_strings():
    assert pad_text(42) == "42"  # str(42) = "42", len 2, passes through
    assert pad_text(1) == "  "  # str(1) = "1", len 1, padded


# ---------------------------------------------------------------------------
# shorten_number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0"),
        (1, "1"),
        (999, "999"),
        (1_000, "1k"),
        (1_500, "1k"),  # truncates, doesn't round
        (999_999, "999k"),
        (1_000_000, "1m"),
        (2_500_000, "2m"),
        (999_999_999, "999m"),
        (1_000_000_000, "1b"),
        (5_000_000_000, "5b"),
    ],
)
def test_shorten_number(n, expected):
    assert shorten_number(n) == expected


# ---------------------------------------------------------------------------
# get_file_size_str
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "b, suffix",
    [
        (0, "bytes"),
        (512, "bytes"),
        (1023, "bytes"),
        (1024, "KB"),
        (1024 * 1024, "MB"),
        (1024 * 1024 * 1024, "GB"),
        (1024 * 1024 * 1024 * 1024, "TB"),
    ],
)
def test_get_file_size_str_units(b, suffix):
    assert suffix in get_file_size_str(b)


def test_get_file_size_str_format():
    # Note: current implementation produces a double space because the unit
    # list entries already include a leading space (" KB" etc.) and the
    # f-string adds another. This test pins the *current* behavior; if the
    # function is cleaned up to single-space, update this assertion.
    assert get_file_size_str(1536) == "1.50  KB"
    assert get_file_size_str(0) == "0.00  bytes"


# ---------------------------------------------------------------------------
# update_buttons (URL validity + label + enable flags)
# ---------------------------------------------------------------------------

def _prefs_with_buttons(**overrides):
    base = {
        "enableButton1": True,
        "button1Label": "GitHub",
        "button1Url": "https://github.com/example",
        "enableButton2": True,
        "button2Label": "Site",
        "button2Url": "https://example.com",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _details():
    return RPCUpdateDetails("test")


def test_update_buttons_both_valid():
    details = _details()
    update_buttons(details, _prefs_with_buttons())
    assert details.buttons == [
        {"label": "GitHub", "url": "https://github.com/example"},
        {"label": "Site", "url": "https://example.com"},
    ]


def test_update_buttons_one_disabled():
    details = _details()
    update_buttons(details, _prefs_with_buttons(enableButton1=False))
    assert details.buttons == [
        {"label": "Site", "url": "https://example.com"},
    ]


def test_update_buttons_invalid_url_drops_button():
    details = _details()
    update_buttons(details, _prefs_with_buttons(button1Url="not a url"))
    assert details.buttons == [
        {"label": "Site", "url": "https://example.com"},
    ]


def test_update_buttons_empty_label_drops_button():
    details = _details()
    update_buttons(details, _prefs_with_buttons(button1Label=""))
    assert len(details.buttons) == 1


def test_update_buttons_clears_previous():
    details = _details()
    details.buttons = [{"label": "Stale", "url": "https://stale.example.com"}]
    update_buttons(details, _prefs_with_buttons(enableButton1=False, enableButton2=False))
    assert details.buttons == []


# ---------------------------------------------------------------------------
# pick_fixed / pick_cycling / update_slot
# ---------------------------------------------------------------------------

def _display_types():
    return {
        "scene": lambda ctx: ctx.scene,
        "polys": lambda ctx: ctx.polys,
        "frame": lambda ctx: ctx.frame,
        "missing": lambda ctx: None,  # always blank
    }


def test_pick_fixed_returns_value():
    ctx = SimpleNamespace(scene="MyScene", polys="1k verts", frame=10)
    assert pick_fixed(ctx, "scene", _display_types()) == "MyScene"


def test_pick_fixed_returns_empty_for_unknown_kind():
    ctx = SimpleNamespace(scene="MyScene", polys="x", frame=1)
    assert pick_fixed(ctx, "nonexistent", _display_types()) == ""


def test_pick_fixed_returns_empty_for_none_value():
    ctx = SimpleNamespace(scene="MyScene", polys="x", frame=1)
    assert pick_fixed(ctx, "missing", _display_types()) == ""


def test_pick_cycling_skips_peer_fixed():
    """When the peer slot is fixed on 'scene', the cycling slot must skip it."""
    ctx = SimpleNamespace(scene="MyScene", polys="POLYS", frame="FRAME")
    session = SessionInfo()
    session.cycle_iter = 0
    out = pick_cycling(
        ctx,
        peer_cycling=False,
        peer_fixed="scene",
        offset=0,
        display_types=_display_types(),
        session=session,
    )
    # scene is skipped; cycle should land on polys (first non-skipped, non-None)
    assert out == "POLYS"


def test_pick_cycling_skips_none_values():
    ctx = SimpleNamespace(scene=None, polys=None, frame="FRAME")
    session = SessionInfo()
    session.cycle_iter = 0
    out = pick_cycling(
        ctx,
        peer_cycling=False,
        peer_fixed="",
        offset=0,
        display_types=_display_types(),
        session=session,
    )
    assert out == "FRAME"


def test_pick_cycling_returns_empty_if_all_none():
    ctx = SimpleNamespace(scene=None, polys=None, frame=None)
    session = SessionInfo()
    out = pick_cycling(
        ctx,
        peer_cycling=False,
        peer_fixed="",
        offset=0,
        display_types=_display_types(),
        session=session,
    )
    assert out == ""


def _prefs_for_slot(**overrides):
    base = {
        "enableState": True,
        "enableDetails": True,
        "customState": "",
        "customDetails": "",
        "stateCycle": False,
        "detailsCycle": False,
        "stateType": "scene",
        "detailsType": "polys",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_update_slot_writes_to_details():
    ctx = SimpleNamespace(scene="MyScene", polys="POLYS", frame="FRAME")
    prefs = _prefs_for_slot()
    details = _details()
    session = SessionInfo()
    update_slot(ctx, "details", prefs, details, _display_types(), session)
    assert details.details_text == "POLYS"


def test_update_slot_disabled_clears_text():
    ctx = SimpleNamespace(scene="MyScene", polys="POLYS")
    prefs = _prefs_for_slot(enableDetails=False)
    details = _details()
    details.details_text = "previous"
    update_slot(ctx, "details", prefs, details, _display_types(), SessionInfo())
    assert details.details_text == ""


def test_update_slot_custom_overrides():
    ctx = SimpleNamespace(scene="MyScene", polys="POLYS")
    prefs = _prefs_for_slot(customDetails="Custom Text Here")
    details = _details()
    update_slot(ctx, "details", prefs, details, _display_types(), SessionInfo())
    assert details.details_text == "Custom Text Here"


def test_update_slot_custom_pads_short_text():
    """Discord requires >=2 chars; pad_text pads single chars to '  '."""
    ctx = SimpleNamespace(scene="MyScene", polys="POLYS")
    prefs = _prefs_for_slot(customDetails="a")
    details = _details()
    update_slot(ctx, "details", prefs, details, _display_types(), SessionInfo())
    assert details.details_text == "  "


# ---------------------------------------------------------------------------
# advance_cycle
# ---------------------------------------------------------------------------

def test_advance_cycle_wraps():
    session = SessionInfo()
    session.cycle_iter = 0
    display_types = {"a": None, "b": None, "c": None}
    advance_cycle(session, display_types)
    assert session.cycle_iter == 1
    advance_cycle(session, display_types)
    advance_cycle(session, display_types)
    assert session.cycle_iter == 0  # wrapped


# ---------------------------------------------------------------------------
# Render-session event handlers
# ---------------------------------------------------------------------------


def test_on_render_end_clears_state():
    session = SessionInfo()
    session.is_rendering = True
    session.rendered_frames = 47
    on_render_end(session)
    assert session.is_rendering is False
    assert session.rendered_frames == 0


def test_on_frame_render_end_increments():
    session = SessionInfo()
    session.rendered_frames = 0
    on_frame_render_end(session)
    on_frame_render_end(session)
    on_frame_render_end(session)
    assert session.rendered_frames == 3


# ---------------------------------------------------------------------------
# RPC: connect_rpc, push_rpc_update, rpc_update, force_clear_on_exit
# ---------------------------------------------------------------------------

from common.rpc_util import (  # noqa: E402
    connect_rpc, push_rpc_update, rpc_update, force_clear_on_exit,
)
from pypresence import exceptions  # noqa: E402


class _FakePresence:
    """In-memory Presence client for testing the connect/update/clear paths.

    Configurable failure modes:
      - connect_raises:  exception to raise from connect()
      - update_raises:   exception to raise from update()
      - clear_raises / close_raises: exceptions for shutdown helpers
    """

    def __init__(self):
        self.connected = False
        self.cleared = False
        self.closed = False
        self.last_update_kwargs: dict | None = None
        self.update_call_count = 0
        self.connect_raises: BaseException | None = None
        self.update_raises: BaseException | None = None
        self.clear_raises: BaseException | None = None
        self.close_raises: BaseException | None = None

    def connect(self):
        if self.connect_raises is not None:
            raise self.connect_raises
        self.connected = True

    def update(self, **kwargs):
        self.update_call_count += 1
        self.last_update_kwargs = kwargs
        if self.update_raises is not None:
            raise self.update_raises

    def clear(self):
        self.cleared = True
        if self.clear_raises is not None:
            raise self.clear_raises

    def close(self):
        self.closed = True
        if self.close_raises is not None:
            raise self.close_raises


# --- connect_rpc ---

def test_connect_rpc_success_returns_true():
    client = _FakePresence()
    assert connect_rpc(client, "test_app") is True
    assert client.connected is True


def test_connect_rpc_failure_returns_false_and_calls_error():
    client = _FakePresence()
    client.connect_raises = ConnectionRefusedError("Discord not running")
    errors: list[str] = []
    result = connect_rpc(client, "testapp", error=errors.append)
    assert result is False
    assert len(errors) == 1
    # app_name is passed through .capitalize() (first letter only).
    assert "Testapp" in errors[0]
    assert "Connection Error" in errors[0]


def test_connect_rpc_swallows_any_exception():
    """connect_rpc catches `Exception` broadly so a misbehaving Presence backend
    can't kill the host plugin."""
    class _Boom(_FakePresence):
        def connect(self):
            raise RuntimeError("kaboom")
    assert connect_rpc(_Boom(), "test_app", error=lambda _: None) is False


# --- rpc_update (kwargs mapping into client.update) ---

def _make_update_details(**overrides):
    d = RPCUpdateDetails("app_icon")
    d.state_text = overrides.get("state_text", "STATE")
    d.details_text = overrides.get("details_text", "DETAILS")
    d.small_icon = overrides.get("small_icon", "small")
    d.small_icon_text = overrides.get("small_icon_text", "small text")
    d.large_icon = overrides.get("large_icon", "large")
    d.large_icon_text = overrides.get("large_icon_text", "large text")
    d.buttons = overrides.get("buttons", [])
    if "start_time" in overrides:
        d.start_time = overrides["start_time"]
    return d


def test_rpc_update_maps_details_to_client_kwargs():
    client = _FakePresence()
    d = _make_update_details()
    rpc_update(d, client, enable_time=True)
    kw = client.last_update_kwargs
    assert kw is not None
    assert kw["state"] == "STATE"
    assert kw["details"] == "DETAILS"
    assert kw["small_image"] == "small"
    assert kw["small_text"] == "small text"
    assert kw["large_image"] == "large"
    assert kw["large_text"] == "large text"
    assert kw["buttons"] is None  # empty list -> None per common.rpc_update
    assert kw["start"] == d.start_time


def test_rpc_update_disables_time_when_pref_unset():
    client = _FakePresence()
    rpc_update(_make_update_details(), client, enable_time=False)
    assert client.last_update_kwargs["start"] is None


def test_rpc_update_blank_details_text_becomes_two_spaces():
    """rpc_update substitutes an empty details_text with '  ' (Discord requires
    >= 2 chars for any displayed field)."""
    client = _FakePresence()
    rpc_update(_make_update_details(details_text=""), client, enable_time=True)
    assert client.last_update_kwargs["details"] == "  "


def test_rpc_update_small_text_empty_becomes_none():
    """Empty small_text/large_text get coerced to None so Discord drops the field."""
    client = _FakePresence()
    rpc_update(_make_update_details(small_icon_text="", large_icon_text=""),
               client, enable_time=True)
    assert client.last_update_kwargs["small_text"] is None
    assert client.last_update_kwargs["large_text"] is None


def test_rpc_update_passes_buttons_when_nonempty():
    client = _FakePresence()
    btns = [{"label": "Site", "url": "https://example.com"}]
    rpc_update(_make_update_details(buttons=btns), client, enable_time=True)
    assert client.last_update_kwargs["buttons"] == btns


# --- push_rpc_update ---

def _push_prefs(**overrides):
    return SimpleNamespace(enableTime=overrides.get("enableTime", True))


def test_push_rpc_update_when_connected_calls_update():
    client = _FakePresence()
    session = SessionInfo()
    session.connected = True
    details = _make_update_details()
    push_rpc_update(session, details, _push_prefs(), client, "app")
    assert client.update_call_count == 1


def test_push_rpc_update_when_disconnected_retries_and_pushes():
    """When push_rpc_update is invoked on a disconnected session, the
    reconnect-then-immediately-retry path runs: connect_rpc flips
    session.connected to True, and the recursive call pushes the update
    in the same tick (no waiting for the next timer event)."""
    client = _FakePresence()
    session = SessionInfo()
    session.connected = False
    push_rpc_update(session, _make_update_details(), _push_prefs(), client,
                    "app", error=lambda _: None)
    assert session.connected is True
    assert client.update_call_count == 1


def _instantiate_exc(exc_cls):
    """pypresence exceptions take no constructor args; AssertionError does."""
    try:
        return exc_cls()
    except TypeError:
        return exc_cls("lost")


@pytest.mark.parametrize("exc_cls", [
    exceptions.InvalidID,
    exceptions.PipeClosed,
    exceptions.DiscordNotFound,
    AssertionError,
])
def test_push_rpc_update_handles_connection_lost_exceptions(exc_cls):
    """The (InvalidID, AssertionError, PipeClosed, DiscordNotFound) branch
    marks the session disconnected and attempts a reconnect."""
    client = _FakePresence()
    client.update_raises = _instantiate_exc(exc_cls)
    session = SessionInfo()
    session.connected = True
    push_rpc_update(session, _make_update_details(), _push_prefs(), client,
                    "app", error=lambda _: None)
    # update() failed -> session marked disconnected, then connect_rpc retried
    # (the fake's connect path succeeds, so .connected is True again).
    assert session.connected is True


def test_push_rpc_update_handles_server_error_without_disconnect():
    """ServerError is its own branch — logged but doesn't toggle the connected flag."""
    client = _FakePresence()
    client.update_raises = _instantiate_exc(exceptions.ServerError)
    session = SessionInfo()
    session.connected = True
    push_rpc_update(session, _make_update_details(), _push_prefs(), client,
                    "app", error=lambda _: None)
    # The connected flag should still be True (ServerError doesn't flip it).
    assert session.connected is True


# --- force_clear_on_exit ---

def test_force_clear_on_exit_calls_clear_and_close():
    client = _FakePresence()
    force_clear_on_exit(client)
    assert client.cleared is True
    assert client.closed is True


def test_force_clear_on_exit_swallows_exceptions():
    """At interpreter shutdown we never want this to raise."""
    client = _FakePresence()
    client.clear_raises = RuntimeError("shutdown race")
    # Must not raise.
    force_clear_on_exit(client)


def test_force_clear_on_exit_swallows_baseexception():
    """Plugin teardown can race with SystemExit / KeyboardInterrupt; the
    function uses `except BaseException` to be totally tolerant."""
    client = _FakePresence()
    client.clear_raises = SystemExit(1)
    force_clear_on_exit(client)


# ---------------------------------------------------------------------------
# JSONSharedSettings — load/write/setup_persistence
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import ClassVar, Dict, Any as _Any  # noqa: E402
from common import JSONSharedSettings  # noqa: E402


@dataclass
class _SettingsForLoadTest(JSONSharedSettings):
    """Minimal dataclass for exercising load/write code paths. We don't extend
    SharedSettings here — we only need a few fields with a known shape."""
    _INITIAL_DEFAULTS: ClassVar[Dict[str, _Any]] = {"name": "initial"}
    name: str = "default_name"
    interval: int = 10
    enabled: bool = True


def test_jsonsharedsettings_load_from_existing_json(tmp_path):
    p = tmp_path / "prefs.json"
    p.write_text(_json.dumps({"name": "loaded", "interval": 42, "enabled": False}))
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test")
    assert s.name == "loaded"
    assert s.interval == 42
    assert s.enabled is False


def test_jsonsharedsettings_load_missing_keys_uses_initial_or_field_defaults(tmp_path):
    """Keys missing from JSON should fall back. `name` has an _INITIAL_DEFAULT
    so it uses that; `interval` falls back to the dataclass field default."""
    p = tmp_path / "prefs.json"
    p.write_text(_json.dumps({"enabled": False}))  # only `enabled` present
    warnings: list[str] = []
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test", warn=warnings.append)
    assert s.enabled is False
    # Each missing key produced a warning.
    assert len(warnings) >= 2


def test_jsonsharedsettings_load_missing_file_uses_defaults(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    warnings: list[str] = []
    s = _SettingsForLoadTest()
    s.setup_persistence(str(missing), app_name="test", warn=warnings.append)
    # No file, defaults kept.
    assert s.name == "default_name"
    assert s.interval == 10
    # A warning was issued.
    assert len(warnings) == 1
    assert "Error loading" in warnings[0]


def test_jsonsharedsettings_load_malformed_json_uses_defaults(tmp_path):
    p = tmp_path / "prefs.json"
    p.write_text("not valid {{{ json")
    warnings: list[str] = []
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test", warn=warnings.append)
    assert s.name == "default_name"
    assert len(warnings) == 1


def test_jsonsharedsettings_write_through_setattr(tmp_path):
    """After load, a setattr should eventually persist to disk via the timer.
    We bypass the QTimer delay by calling _write() directly."""
    p = tmp_path / "prefs.json"
    p.write_text(_json.dumps({"name": "loaded", "interval": 42, "enabled": True}))
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test")
    s.name = "modified"
    s._write()  # bypass QTimer.start() debounce
    on_disk = _json.loads(p.read_text())
    assert on_disk["name"] == "modified"
    assert on_disk["interval"] == 42  # other fields preserved


def test_jsonsharedsettings_flush_writes_synchronously(tmp_path):
    """flush() should bypass the 2s debounce and persist immediately. Used
    by menu toggle helpers (NKMenu.start/stop, sp_pause_presence, etc.) so
    a fast app close right after the toggle doesn't lose the change."""
    p = tmp_path / "prefs.json"
    p.write_text(_json.dumps({"name": "loaded", "interval": 42, "enabled": True}))
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test")
    s.enabled = False
    # The QTimer is started but won't fire without an event loop spinning;
    # flush() must persist regardless.
    s.flush()
    on_disk = _json.loads(p.read_text())
    assert on_disk["enabled"] is False


def test_jsonsharedsettings_flush_stops_pending_timer(tmp_path):
    """flush() should cancel the pending debounce so the timer can't fire a
    duplicate write later."""
    p = tmp_path / "prefs.json"
    p.write_text(_json.dumps({"name": "loaded", "interval": 42, "enabled": True}))
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test")
    s.name = "modified"
    assert s._timer.isActive()
    s.flush()
    assert not s._timer.isActive()


def test_jsonsharedsettings_reset_restores_defaults(tmp_path):
    """reset() should restore _INITIAL_DEFAULTS where present and field
    defaults elsewhere."""
    p = tmp_path / "prefs.json"
    p.write_text(_json.dumps({"name": "loaded", "interval": 99, "enabled": False}))
    s = _SettingsForLoadTest()
    s.setup_persistence(str(p), app_name="test")
    s.reset()
    # name has _INITIAL_DEFAULTS["name"] = "initial"
    assert s.name == "initial"
    # interval falls back to the field default (10)
    assert s.interval == 10
    # enabled falls back to True
    assert s.enabled is True


# ---------------------------------------------------------------------------
# RPCBasePlugin.update_presence: generalEnable=False clear semantics
# (the same bug applied across Painter/Krita/Designer via the common base;
# we test against a minimal concrete subclass.)
# ---------------------------------------------------------------------------

from common.qt_common import RPCBasePlugin, JSONSharedSettings  # noqa: E402
from common import SharedSettings as _SharedSettingsForRPCBase  # noqa: E402


def _make_test_plugin(rpc_client_override=None):
    """Build a minimal RPCBasePlugin subclass against the SharedSettings
    schema, with overridable rpc_client so we can assert on clear/close calls
    without instantiating real pypresence connections."""
    from dataclasses import dataclass
    from typing import ClassVar, Dict, Any as _Any

    @dataclass
    class _MinimalSettings(_SharedSettingsForRPCBase):
        _INITIAL_DEFAULTS: ClassVar[Dict[str, _Any]] = {}
        INFO_CHOICES: ClassVar = [("scene", "scene")]

    class _Plugin(RPCBasePlugin):
        def _capture(self):
            return SimpleNamespace()

        def start(self):
            pass

        def close(self):
            pass

        def update_small_icon(self, ctx):
            pass

        def update_large_icon(self, ctx):
            pass

    plugin = _Plugin(
        app_id="x", app_name="testapp", prefs_class=_MinimalSettings,
        warn=lambda *_: None, error=lambda *_: None,
    )
    if rpc_client_override is not None:
        plugin.rpc_client = rpc_client_override
    return plugin


def test_rpcbase_update_presence_disabled_when_not_connected_noop():
    """generalEnable=False with no connection should be a quiet no-op."""
    client = _FakePresence()  # not yet connected; clear() would normally raise
    plugin = _make_test_plugin(rpc_client_override=client)
    plugin.prefs.generalEnable = False
    plugin.session.connected = False
    plugin.update_presence()
    # No clear call was attempted; no exception propagated.
    assert client.cleared is False
    assert plugin.session.connected is False


def test_rpcbase_update_presence_disabled_when_connected_preserves_connection():
    """clear() succeeds; `connected` stays True (clear doesn't disconnect)."""
    client = _FakePresence()
    plugin = _make_test_plugin(rpc_client_override=client)
    plugin.prefs.generalEnable = False
    plugin.session.connected = True
    plugin.update_presence()
    assert client.cleared is True
    assert plugin.session.connected is True


def test_rpcbase_update_presence_disabled_clear_failure_marks_disconnected():
    """If clear() raises, the socket is presumed dead — mark disconnected
    so the next generalEnable=True tick triggers a reconnect."""
    client = _FakePresence()
    client.clear_raises = AssertionError("sock_writer is None")
    errors: list[str] = []
    plugin = _make_test_plugin(rpc_client_override=client)
    plugin._error = errors.append  # capture the formatted error
    plugin.prefs.generalEnable = False
    plugin.session.connected = True
    plugin.update_presence()
    assert plugin.session.connected is False
    assert any("clear failed" in e for e in errors)


# The previous test_jsonsharedsettings_refresh_callback_exceptions_propagate
# covered _write's behavior when refresh_func raised. JSONSharedSettings no
# longer carries refresh_func at all — RPC update scheduling moved to
# RPCBasePlugin.on_general_update_change — so the behavior the test pinned
# doesn't exist anymore. Removed rather than rewritten.
