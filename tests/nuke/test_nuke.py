"""
Tests for NKContext (Nuke plugin).

The plugin uses module-level globals (NK_PREFS, NK_MENU, NK_WORKER) rather
than the class-based RPCBasePlugin pattern, but NKContext is the testable
piece — its methods read from nuke.* at call time, so configuring the fake
between tests works the same as in painter/krita.

Bugs flagged by docs cross-check, with regression tests marked
xfail(strict=True) so they pass-when-fixed:
  * get_io_nodes uses 'read_node'/'write_node' (with underscores) when both
    read and write nodes exist, but 'read node'/'write node' (with spaces)
    when only one side exists. See test_get_io_nodes_plurals_use_space.
  * nk_handle_active_node checks node[0] (the node name) against the
    NK_HD_ICONS/NK_UPSCALED_ICONS class lists, so the "node has a small
    icon, skip its text" deduplication never works — the text always
    duplicates the icon. Should be node[1] (the class). See
    test_nk_handle_active_node_*.
"""
from __future__ import annotations
import pytest

# Importing the menu module triggers module-level setup: NK_PREFS, NK_MENU,
# NK_WORKER thread, render callback installation. All goes through the fake.
from nuke_presence.menu import NKContext, NK_WORKER


# ---------------------------------------------------------------------------
# NK_WORKER thread lifecycle
# ---------------------------------------------------------------------------

def test_nk_worker_thread_started_at_import():
    """Regression: NKBackgroundWorker.start() must be called at module load
    (the worker's _run loop is the only thing that periodically calls
    nk_update_presence — without it, Discord only ever sees the one update
    fired manually by the settings-dialog reset path)."""
    assert NK_WORKER._thread.is_alive()


def test_nk_worker_thread_is_daemon():
    """Daemon = True so the thread doesn't block Nuke from exiting on its
    own; cleanup goes through atexit / NKMenu.stop, not thread.join."""
    assert NK_WORKER._thread.daemon is True


# ---------------------------------------------------------------------------
# get_app_str
# ---------------------------------------------------------------------------

def test_get_app_str_nuke_commercial(nk):
    nk.env.update({"studio": False, "nukex": False, "indie": False, "nc": False})
    ctx = NKContext()
    # NK_IS_COMMERCIAL is computed at module import — see "Module-level setup"
    # note in conftest. The test confirms format only.
    out = ctx.get_app_str(include_version=False)
    assert out.startswith("Nuke")


def test_get_app_str_with_version(nk):
    nk.env.update({"NukeVersionString": "17.0.1", "studio": False, "nukex": False})
    ctx = NKContext()
    out = ctx.get_app_str(include_version=True)
    assert "17.0.1" in out


def test_get_app_str_nukex(nk):
    nk.env.update({"studio": False, "nukex": True})
    ctx = NKContext()
    assert ctx.get_app_str().startswith("NukeX")


def test_get_app_str_nukestudio(nk):
    nk.env.update({"studio": True, "nukex": False})
    ctx = NKContext()
    assert ctx.get_app_str().startswith("NukeStudio")


# ---------------------------------------------------------------------------
# Memory + frame
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("byts, expected_unit", [
    (0, "bytes"),
    (1024, "KB"),
    (1024 * 1024, "MB"),
    (1024 * 1024 * 1024, "GB"),
])
def test_get_memory_usage(nk, byts, expected_unit):
    nk.set_state(memory_bytes=byts)
    ctx = NKContext()
    out = ctx.get_memory_usage()
    assert out.startswith("Using ")
    assert expected_unit in out


@pytest.mark.parametrize("f", [1, 17, 100, 9999])
def test_get_frame(nk, f):
    nk.set_state(frame_value=f)
    ctx = NKContext()
    assert ctx.get_frame_info() == f"Frame {f} (24.0fps)"


@pytest.mark.parametrize("start, end", [(1, 100), (101, 250), (0, 0)])
def test_get_frame_range(nk, start, end):
    nk.set_state(root=nk.make_root(frame_range=(start, end)))
    ctx = NKContext()
    assert ctx.get_frame_range() == (start, end)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def test_get_active_node_none_when_no_selection(nk):
    nk.set_state(selected_node=None)
    ctx = NKContext()
    assert ctx.get_active_node() is None


def test_get_active_node_returns_name_class_tuple(nk):
    nk.set_state(selected_node=nk.make_node(name="Blur1", node_class="Blur"))
    ctx = NKContext()
    assert ctx.get_active_node() == ("Blur1", "Blur")


def test_get_io_nodes_no_io_returns_none(nk):
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={"Read": [], "Write": []})
    ctx = NKContext()
    assert ctx.get_io_nodes() is None


def test_get_io_nodes_reads_only(nk):
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={
        "Read": [nk.make_node(node_class="Read") for _ in range(3)],
        "Write": [],
    })
    ctx = NKContext()
    assert ctx.get_io_nodes() == "3 read nodes"


def test_get_io_nodes_writes_only(nk):
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={
        "Read": [],
        "Write": [nk.make_node(node_class="Write") for _ in range(2)],
    })
    ctx = NKContext()
    assert ctx.get_io_nodes() == "2 write nodes"


# allNodes() is documented to return list, but in practice Nuke can return
# None or print uncatchable RuntimeError-like messages in some license/version
# combinations (e.g. non-commercial with >10 selected nodes; behavior shifted
# between 17.0v1 and 17.0v2). The plugin's defensive None branches cover that,
# so these tests are real coverage, not dead-code tests.
def test_get_io_nodes_both_none_returns_none(nk):
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={"Read": None, "Write": None})
    ctx = NKContext()
    assert ctx.get_io_nodes() is None


def test_get_io_nodes_only_read_none(nk):
    """Read is None, Write has nodes — fall through to the elif write branch."""
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={
        "Read": None,
        "Write": [nk.make_node(node_class="Write") for _ in range(2)],
    })
    ctx = NKContext()
    assert ctx.get_io_nodes() == "2 write nodes"


def test_get_io_nodes_only_write_none(nk):
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={
        "Read": [nk.make_node(node_class="Read") for _ in range(4)],
        "Write": None,
    })
    ctx = NKContext()
    assert ctx.get_io_nodes() == "4 read nodes"


def test_get_io_nodes_one_none_one_empty_returns_none(nk):
    """One side None, other side empty list — nothing to report."""
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={"Read": None, "Write": []})
    ctx = NKContext()
    assert ctx.get_io_nodes() is None


def test_get_num_nodes_noncommercial_uses_root_numnodes(nk, monkeypatch):
    """Non-commercial Nuke can't recurse into groups, so we use
    nuke.root().numNodes() instead of len(allNodes(recurseGroups=True))."""
    import nuke_presence.menu as nk_menu
    monkeypatch.setattr(nk_menu, "NK_IS_COMMERCIAL", False)
    nk.set_state(root=nk.make_root(num_nodes=27))
    ctx = NKContext()
    assert ctx.get_num_nodes() == "27 nodes"


def test_get_num_nodes_commercial_uses_all_nodes(nk, monkeypatch):
    """Commercial Nuke uses len(allNodes(recurseGroups=True)) to include
    nested-group children."""
    import nuke_presence.menu as nk_menu
    monkeypatch.setattr(nk_menu, "NK_IS_COMMERCIAL", True)
    nk.set_state(all_nodes={None: [nk.make_node(name=f"n{i}") for i in range(13)]})
    ctx = NKContext()
    assert ctx.get_num_nodes() == "13 nodes"


def test_get_viewer_str_with_non_rgba_channels(nk):
    """Any non-empty channels string gets parenthesized in the output."""
    upstream = nk.make_node(name="Read1", node_class="Read")
    viewer_node = nk.make_node(
        name="Viewer1",
        node_class="Viewer",
        knobs={"channels": "alpha", "viewerProcess": "sRGB"},
        inputs={0: upstream},
    )
    nk.set_state(active_viewer=nk.make_viewer(node=viewer_node, active_input=0))
    ctx = NKContext()
    out = ctx.get_viewer_str()
    assert out is not None
    assert "(alpha)" in out
    assert "Read1" in out
    # sRGB is the default viewerProcess and is suppressed.
    assert "sRGB" not in out


def test_get_viewer_str_empty_channels_omitted(nk):
    """Empty channels value is treated as falsy and the (channels) parens
    are dropped from the output entirely."""
    upstream = nk.make_node(name="Blur1", node_class="Blur")
    viewer_node = nk.make_node(
        name="Viewer1",
        node_class="Viewer",
        knobs={"channels": "", "viewerProcess": ""},
        inputs={0: upstream},
    )
    nk.set_state(active_viewer=nk.make_viewer(node=viewer_node, active_input=0))
    ctx = NKContext()
    out = ctx.get_viewer_str()
    assert out is not None
    assert "(" not in out  # no channels parens


def test_get_scaling_info_with_downrez(nk):
    """downrez != 1 with proxy off triggers the scaling-info branch."""
    viewer_node = nk.make_node(
        name="Viewer1", node_class="Viewer",
        knobs={"downrez": 4},
    )
    nk.set_state(
        root=nk.make_root(proxy=False, proxy_scale=1.0),
        active_viewer=nk.make_viewer(node=viewer_node, active_input=0),
    )
    ctx = NKContext()
    out = ctx.get_scaling_info()
    assert out is not None
    assert "1/4" in out


def test_get_scaling_info_with_both_proxy_and_downrez(nk):
    viewer_node = nk.make_node(
        name="Viewer1", node_class="Viewer",
        knobs={"downrez": 2},
    )
    nk.set_state(
        root=nk.make_root(proxy=True, proxy_scale=0.25),
        active_viewer=nk.make_viewer(node=viewer_node, active_input=0),
    )
    ctx = NKContext()
    out = ctx.get_scaling_info()
    assert out is not None
    assert "0.25" in out
    assert "1/2" in out


def test_get_io_nodes_both_present(nk):
    """Both read and write nodes — verify both counts come through correctly.
    (Earlier audit had this flagged as buggy; current code at menu.py:140 is
    correct: f-string uses len(write_nodes), not len(read_nodes).)"""
    from nuke_presence.menu import NK_PREFS
    NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={
        "Read": [nk.make_node(node_class="Read") for _ in range(3)],
        "Write": [nk.make_node(node_class="Write") for _ in range(5)],
    })
    ctx = NKContext()
    out = ctx.get_io_nodes()
    assert "3 read" in out
    assert "5 write" in out


# ---------------------------------------------------------------------------
# Layers + format + viewer + color management
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("layers, expected", [
    ([], "0 layers"),
    (["rgba"], "1 layer"),
    (["rgba", "depth"], "2 layers"),
    (["rgba", "depth", "motion", "id"], "4 layers"),
])
def test_get_num_layers(nk, layers, expected):
    nk.set_state(layers_list=layers)
    ctx = NKContext()
    assert ctx.get_num_layers() == expected


def test_get_viewer_str_none_when_no_active_viewer(nk):
    nk.set_state(active_viewer=None)
    ctx = NKContext()
    assert ctx.get_viewer_str() is None


def test_get_viewer_str_none_when_no_upstream(nk):
    # Viewer exists but its node has no input at active_input idx.
    viewer_node = nk.make_node(name="Viewer1", node_class="Viewer", knobs={"channels": "rgba"})
    nk.set_state(active_viewer=nk.make_viewer(node=viewer_node, active_input=0))
    ctx = NKContext()
    assert ctx.get_viewer_str() is None


def test_get_viewer_str_with_upstream(nk):
    """sRGB is the default viewer process; it's omitted from the output."""
    upstream = nk.make_node(name="Blur1", node_class="Blur")
    viewer_node = nk.make_node(
        name="Viewer1",
        node_class="Viewer",
        knobs={"channels": "rgba", "viewerProcess": "sRGB"},
        inputs={0: upstream},
    )
    nk.set_state(active_viewer=nk.make_viewer(node=viewer_node, active_input=0))
    ctx = NKContext()
    out = ctx.get_viewer_str()
    assert out is not None
    assert "Blur1" in out
    # Channels are always shown when truthy. sRGB viewerProcess is suppressed
    # since it's the default.
    assert "(rgba)" in out
    assert "sRGB" not in out


def test_get_viewer_str_non_srgb_viewerprocess_included(nk):
    """A non-sRGB viewerProcess is reflected with 'in' prefix."""
    upstream = nk.make_node(name="Read1", node_class="Read")
    viewer_node = nk.make_node(
        name="Viewer1",
        node_class="Viewer",
        knobs={"channels": "rgba", "viewerProcess": "Rec709"},
        inputs={0: upstream},
    )
    nk.set_state(active_viewer=nk.make_viewer(node=viewer_node, active_input=0))
    ctx = NKContext()
    out = ctx.get_viewer_str()
    assert "in Rec709" in out


def test_get_color_management(nk):
    nk.set_state(root=nk.make_root(color_mgmt="OCIO"))
    ctx = NKContext()
    assert ctx.get_color_management() == "Color management: OCIO"


def test_get_format_str(nk):
    nk.set_state(root=nk.make_root(format_obj=nk.make_format("HD_1080", 1920, 1080)))
    ctx = NKContext()
    # Underscores in the format name are stripped to spaces.
    assert ctx.get_format_str() == "HD 1080 (1920x1080)"


# ---------------------------------------------------------------------------
# Comp name (script-name RuntimeError branch)
# ---------------------------------------------------------------------------

def test_get_comp_name_unsaved_raises_runtimeerror(nk):
    nk.set_state(raise_script_name=True)
    ctx = NKContext()
    assert ctx.get_comp_name() == "Unsaved Script"


def test_get_comp_name_saved(nk):
    nk.set_state(script_name_str="/path/to/myscript.nk")
    ctx = NKContext()
    assert ctx.get_comp_name() == "myscript.nk"


# ---------------------------------------------------------------------------
# FPS + scaling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0, 23.976])
def test_get_fps(nk, fps):
    nk.set_state(root=nk.make_root(fps=fps))
    ctx = NKContext()
    assert ctx.get_fps() == fps


def test_get_scaling_info_default_returns_none(nk):
    # proxy=False, downrez=1 by default; should return None.
    nk.set_state(root=nk.make_root(proxy=False, proxy_scale=1.0))
    nk.set_state(active_viewer=None)
    ctx = NKContext()
    assert ctx.get_scaling_info() is None


def test_get_scaling_info_proxy_active(nk):
    nk.set_state(root=nk.make_root(proxy=True, proxy_scale=0.5))
    # Viewer not needed when proxy is active.
    nk.set_state(active_viewer=None)
    ctx = NKContext()
    out = ctx.get_scaling_info()
    assert out is not None
    assert "0.5" in out


# ---------------------------------------------------------------------------
# nk_update_small_icon / nk_update_large_icon / nk_update_presence_details
# ---------------------------------------------------------------------------

from nuke_presence.menu import (  # noqa: E402
    nk_update_small_icon, nk_update_large_icon, nk_update_presence_details,
    NK_PREFS, NK_SESSION, NK_UPDATE_DETAILS,
)


@pytest.fixture
def nuke_globals_clean():
    """Snapshot/restore module-level Nuke globals.

    `cleared` is reset going *in* as well as out: nk_update_presence only
    clears on the transition into the disabled state, so a test that leaves it
    set would silently suppress the clear in the next test."""
    snap = (
        NK_PREFS.displaySmallIcon, NK_PREFS.displayVersion,
        NK_PREFS.enableDetails, NK_PREFS.displayRenderStats, NK_PREFS.displayFrames,
        NK_SESSION.is_rendering, NK_SESSION.cleared,
        NK_UPDATE_DETAILS.small_icon, NK_UPDATE_DETAILS.small_icon_text,
        NK_UPDATE_DETAILS.large_icon, NK_UPDATE_DETAILS.large_icon_text,
        NK_UPDATE_DETAILS.details_text,
    )
    NK_SESSION.cleared = False
    yield
    (NK_PREFS.displaySmallIcon, NK_PREFS.displayVersion,
     NK_PREFS.enableDetails, NK_PREFS.displayRenderStats, NK_PREFS.displayFrames,
     NK_SESSION.is_rendering, NK_SESSION.cleared,
     NK_UPDATE_DETAILS.small_icon, NK_UPDATE_DETAILS.small_icon_text,
     NK_UPDATE_DETAILS.large_icon, NK_UPDATE_DETAILS.large_icon_text,
     NK_UPDATE_DETAILS.details_text) = snap


def test_update_small_icon_disabled_pref_resets(nk, nuke_globals_clean):
    NK_PREFS.displaySmallIcon = False
    nk.set_state(selected_node=nk.make_node(name="Blur1", node_class="Blur"))
    ctx = NKContext()
    nk_update_small_icon(ctx)
    assert NK_UPDATE_DETAILS.small_icon is None
    assert NK_UPDATE_DETAILS.small_icon_text == ""


def test_update_small_icon_no_selection_clears(nk, nuke_globals_clean):
    NK_PREFS.displaySmallIcon = True
    nk.set_state(selected_node=None)
    ctx = NKContext()
    nk_update_small_icon(ctx)
    assert NK_UPDATE_DETAILS.small_icon is None
    assert NK_UPDATE_DETAILS.small_icon_text == ""


@pytest.mark.parametrize("node_class, expected_icon", [
    ("Blur", "blur"),
    ("Read", "read"),
    ("ColorCorrect", "colorcorrect"),
    ("CornerPin", "cornerpin"),
])
def test_update_small_icon_active_node_sets_icon(nk, nuke_globals_clean,
                                                  node_class, expected_icon):
    NK_PREFS.displaySmallIcon = True
    nk.set_state(selected_node=nk.make_node(name="N1", node_class=node_class))
    ctx = NKContext()
    nk_update_small_icon(ctx)
    assert NK_UPDATE_DETAILS.small_icon == expected_icon
    # Hover text: "<name> (<class>)"
    assert NK_UPDATE_DETAILS.small_icon_text == f"N1 ({node_class})"


def test_update_large_icon_with_version(nk, nuke_globals_clean):
    NK_PREFS.displayVersion = True
    nk.env.update({"NukeVersionString": "17.0.1", "studio": False, "nukex": False})
    ctx = NKContext()
    nk_update_large_icon(ctx)
    assert NK_UPDATE_DETAILS.large_icon == "nuke"
    assert "17.0.1" in NK_UPDATE_DETAILS.large_icon_text
    assert "Nuke" in NK_UPDATE_DETAILS.large_icon_text


def test_update_large_icon_without_version(nk, nuke_globals_clean):
    NK_PREFS.displayVersion = False
    nk.env.update({"NukeVersionString": "17.0.1", "studio": False, "nukex": False})
    ctx = NKContext()
    nk_update_large_icon(ctx)
    assert NK_UPDATE_DETAILS.large_icon == "nuke"
    assert "17.0.1" not in NK_UPDATE_DETAILS.large_icon_text


def test_update_presence_details_rendering_branch(nk, nuke_globals_clean):
    """Rendering format includes 'Rendering', the comp name, and the frame
    range; fps is no longer surfaced (removed from the format string)."""
    NK_PREFS.enableDetails = True
    NK_PREFS.displayFrames = True
    NK_SESSION.is_rendering = True
    nk.set_state(
        root=nk.make_root(frame_range=(1, 100), fps=24.0),
        script_name_str="/p/comp01.nk",
    )
    ctx = NKContext()
    nk_update_presence_details(ctx)
    out = NK_UPDATE_DETAILS.details_text
    assert "Rendering" in out
    assert "comp01.nk" in out


# ---------------------------------------------------------------------------
# nk_update_presence: generalEnable=False clear semantics
# ---------------------------------------------------------------------------

from nuke_presence.menu import nk_update_presence, NK_RPC_CLIENT  # noqa: E402


def test_nk_update_presence_disabled_when_not_connected_is_noop(nk, nuke_globals_clean):
    """generalEnable=False + not-connected: skip clear (avoids pypresence's
    sock_writer assertion), leave connected as it was."""
    NK_PREFS.generalEnable = False
    NK_SESSION.connected = False
    nk_update_presence()
    assert NK_SESSION.connected is False


def test_nk_update_presence_disabled_when_connected_preserves_connection(
    nk, nuke_globals_clean, monkeypatch
):
    NK_PREFS.generalEnable = False
    NK_SESSION.connected = True
    calls: list[int] = []
    monkeypatch.setattr(NK_RPC_CLIENT, "clear", lambda: calls.append(1))
    nk_update_presence()
    assert len(calls) == 1
    assert NK_SESSION.connected is True


def test_nk_update_presence_disabled_clears_once_not_every_tick(
    nk, nuke_globals_clean, monkeypatch
):
    """The worker ticks every generalUpdate seconds while disabled; clearing
    an already-cleared presence on each of those is pointless traffic."""
    NK_PREFS.generalEnable = False
    NK_SESSION.connected = True
    calls: list[int] = []
    monkeypatch.setattr(NK_RPC_CLIENT, "clear", lambda: calls.append(1))
    nk_update_presence()
    nk_update_presence()
    nk_update_presence()
    assert len(calls) == 1
    assert NK_SESSION.cleared is True


def test_nk_update_presence_disabled_clear_failure_marks_disconnected(
    nk, nuke_globals_clean, monkeypatch
):
    NK_PREFS.generalEnable = False
    NK_SESSION.connected = True
    def _boom():
        raise AssertionError("sock_writer is None")
    monkeypatch.setattr(NK_RPC_CLIENT, "clear", _boom)
    nk_update_presence()
    assert NK_SESSION.connected is False
    # nuke.warning was used to log the failure.
    assert any("clear failed" in w for w in nk._state.warn_messages)


def test_update_presence_details_rendering_frames_disabled(nk, nuke_globals_clean):
    """displayFrames=False suppresses the 'Frame X of Y' suffix."""
    NK_PREFS.enableDetails = True
    NK_PREFS.displayFrames = False
    NK_SESSION.is_rendering = True
    nk.set_state(
        root=nk.make_root(frame_range=(1, 100), fps=24.0),
        script_name_str="/p/comp02.nk",
    )
    ctx = NKContext()
    nk_update_presence_details(ctx)
    out = NK_UPDATE_DETAILS.details_text
    assert "Rendering" in out
    assert "comp02.nk" in out
    assert "Frame" not in out


def test_update_presence_details_disabled_clears(nk, nuke_globals_clean):
    NK_PREFS.enableDetails = False
    NK_UPDATE_DETAILS.details_text = "stale text"
    ctx = NKContext()
    nk_update_presence_details(ctx)
    assert NK_UPDATE_DETAILS.details_text == ""


def test_update_presence_details_not_rendering_delegates_to_slot(nk, nuke_globals_clean):
    """Non-rendering enableDetails branch goes through update_slot which respects
    detailsType. Set detailsType=comp_name and verify the comp name appears."""
    NK_PREFS.enableDetails = True
    NK_PREFS.detailsType = "comp_name"
    NK_PREFS.customDetails = ""
    NK_PREFS.detailsCycle = False
    NK_SESSION.is_rendering = False
    nk.set_state(script_name_str="/p/comp02.nk")
    ctx = NKContext()
    nk_update_presence_details(ctx)
    assert "comp02.nk" in NK_UPDATE_DETAILS.details_text


from nuke_presence.menu import NK_PREFS as _NK_PREFS  # noqa: E402


def test_get_io_nodes_both_present_plurals_use_space(nk):
    _NK_PREFS.disableNodeQueries = False
    nk.set_state(all_nodes={
        "Read": [nk.make_node(node_class="Read") for _ in range(3)],
        "Write": [nk.make_node(node_class="Write") for _ in range(5)],
    })
    ctx = NKContext()
    out = ctx.get_io_nodes()
    assert "read_node" not in out
    assert "write_node" not in out
    assert "3 read nodes" in out
    assert "5 write nodes" in out


# ---------------------------------------------------------------------------
# nk_handle_active_node coverage. The function decides, in cycle mode,
# whether to surface the active-node text in the details/state slot or
# defer to the small icon. It checks whether the node's class has an icon
# in NK_HD_ICONS / NK_UPSCALED_ICONS — but the current code reads node[0]
# (the node NAME) instead of node[1] (the node CLASS), so the icon check
# is effectively always 'no icon', and the text path is always taken.
# ---------------------------------------------------------------------------

from nuke_presence.menu import nk_handle_active_node  # noqa: E402


def test_nk_handle_active_node_unknown_class_returns_text(nk, nuke_globals_clean):
    """A selected node whose class is NOT in either icon list has no small
    icon to defer to, so the cycle should surface the text."""
    _NK_PREFS.detailsCycle = True
    _NK_PREFS.detailsType = "active_node"
    _NK_PREFS.stateCycle = True
    _NK_PREFS.displaySmallIcon = True
    nk.set_state(selected_node=nk.make_node(name="MyCustomNode1",
                                            node_class="NotAnIconClass"))
    ctx = NKContext()
    out = nk_handle_active_node(ctx)
    assert out == "MyCustomNode1 (NotAnIconClass)"


def test_nk_handle_active_node_known_class_in_cycle_defers_to_icon(nk, nuke_globals_clean):
    """When the selected node's class is in NK_ICONS and icons are on, the
    cycle should return None so the text doesn't double up with the small
    icon. (NK_HD_ICONS and NK_UPSCALED_ICONS were merged into a single
    NK_ICONS catalog, and the disableUpscaledNodes pref was removed.)"""
    _NK_PREFS.detailsCycle = True
    _NK_PREFS.detailsType = "comp_name"  # not fixed-active
    _NK_PREFS.stateCycle = True
    _NK_PREFS.stateType = "comp_name"
    _NK_PREFS.displaySmallIcon = True
    # 'Blur' is in NK_ICONS, so the small icon will show "Blur1 (Blur)".
    nk.set_state(selected_node=nk.make_node(name="Blur1", node_class="Blur"))
    ctx = NKContext()
    assert nk_handle_active_node(ctx) is None
