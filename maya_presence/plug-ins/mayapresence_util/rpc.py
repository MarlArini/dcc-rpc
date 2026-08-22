"""RPC functionality: handling static/cycling fields and updating details struct."""
import maya.cmds as cmds # pyright: ignore[reportMissingImports] pylint: disable=import-error


from common import (
    update_buttons,
    advance_cycle,
    update_slot,
    format_render_details
)

from .context import MPContext
from .shared_state import MP_UPDATE_DETAILS, MP_PREFS, MP_SESSION, mp_print, _get_worker

#################
# Rich Presence #
#################


def mp_update_large_icon(ctx: MPContext):
    MP_UPDATE_DETAILS.large_icon = "maya"
    if MP_PREFS.displayVersion:
        MP_UPDATE_DETAILS.large_icon_text = f"Maya {ctx.get_version_str()}"
    else:
        MP_UPDATE_DETAILS.large_icon_text = "Maya"


def mp_update_small_icon_rendering(ctx: MPContext):
    icon_file_name = None
    icon_text = ""
    # No icons for Maya Software / Maya Hardware
    engines = ["Arnold", "Redshift", "RenderMan", "V-Ray", "Octane"]
    current_engine = ctx.get_render_engine_str()
    if current_engine in engines:
        icon_file_name = current_engine.lower().replace("-", "")
        icon_text = current_engine
    # GPU
    if MP_PREFS.displayGPU:
        gpustr = ctx.get_gpu_str()
        if gpustr and icon_text:
            icon_text += " | " + gpustr
    return icon_file_name, icon_text


def mp_update_small_icon_tool():
    icon_file_name = None
    icon_text = ""
    tc = cmds.currentCtx()
    if (
        tc.startswith("poly")
        or tc.startswith("manip")
        or tc.startswith("curve")
        or tc.startswith("target")
    ):
        icon_file_name = "modeling"
        icon_text = "Modeling"
    elif tc.startswith("sculpt"):
        icon_file_name = "sculpt"
        icon_text = "Sculpting"
    elif tc.startswith("tex"):
        icon_file_name = "uv"
        icon_text = "UV Editing"
    elif tc.startswith("joint") or tc.startswith("ik") or tc.startswith("skin"):
        icon_file_name = "pose"
        icon_text = "Rigging"
    elif tc.startswith("keyframe") or tc.startswith("filter"):
        icon_file_name = "animation"
        icon_text = "Animation"
    return icon_file_name, icon_text


def mp_update_small_icon(ctx: MPContext):
    icon_file_name = None
    icon_text = ""
    if not MP_PREFS.displaySmallIcon:
        MP_UPDATE_DETAILS.small_icon = icon_file_name
        MP_UPDATE_DETAILS.small_icon_text = icon_text
        return
    if MP_PREFS.displayEngine and MP_SESSION.is_rendering:
        icon_file_name, icon_text = mp_update_small_icon_rendering(ctx)
    else:
        try:
            # "Modeling - Expert", "Pose Sculpting", etc.
            space_name = (
                cmds.workspaceLayoutManager(query=True, current=True) or ""
            ).lower()
        except Exception:
            space_name = ""
        if space_name and space_name != "general":
            icon_file_name = (
                space_name[: space_name.find(" ")]
                if space_name.find(" ") > 0
                else space_name
            )
            icon_text = space_name.title()
        else:
            icon_file_name, icon_text = mp_update_small_icon_tool()
    MP_UPDATE_DETAILS.small_icon = icon_file_name
    MP_UPDATE_DETAILS.small_icon_text = icon_text


MP_DISPLAY_TYPES = {
    "scene": lambda ctx: ctx.get_current_scene(),
    "mesh": lambda ctx: ctx.get_mesh_count(),
    "poly": lambda ctx: ctx.get_poly_count_str(),
    "joint": lambda ctx: ctx.get_joint_count(),
    "light": lambda ctx: ctx.get_light_count(),
    "cam": lambda ctx: ctx.get_cam_count(),
    "blendshape": lambda ctx: ctx.get_blendshape_count(),
    "mat": lambda ctx: ctx.get_mat_count(),
    "tex": lambda ctx: ctx.get_tex_count(),
    "size": lambda ctx: ctx.get_file_size(),
    "frame": lambda ctx: ctx.get_current_frame(),
    "active": lambda ctx: ctx.get_active_object(),
    "context": lambda ctx: ctx.get_user_context(),
}


def mp_update_presence_details(ctx: MPContext):
    # Rendering Details
    if MP_PREFS.enableDetails and MP_SESSION.is_rendering:
        res = ctx.get_render_resolution()
        fname = ctx.get_file_name()
        MP_UPDATE_DETAILS.details_text = format_render_details(
            file_name=fname,
            res=res,
            rendered_frames=MP_SESSION.rendered_frames,
            prefs=MP_PREFS
        )
    elif MP_PREFS.enableDetails:
        update_slot(
            ctx, "details", MP_PREFS, MP_UPDATE_DETAILS, MP_DISPLAY_TYPES, MP_SESSION
        )
    else:
        MP_UPDATE_DETAILS.details_text = "  "


def mp_update_presence_state(ctx: MPContext):
    update_slot(ctx, "state", MP_PREFS, MP_UPDATE_DETAILS, MP_DISPLAY_TYPES, MP_SESSION)


def mp_update_presence():
    try:
        if MP_PREFS.detailsCycle or MP_PREFS.stateCycle:
            advance_cycle(MP_SESSION, MP_DISPLAY_TYPES)
        ctx = MPContext.capture()
        mp_update_large_icon(ctx)
        mp_update_small_icon(ctx)
        mp_update_presence_state(ctx)
        mp_update_presence_details(ctx)
        update_buttons(MP_UPDATE_DETAILS, MP_PREFS)
        MP_UPDATE_DETAILS.start_time = MP_SESSION.start_time
    except Exception as e:  # noqa: BLE001
        # MP_UPDATE_DETAILS is half-rewritten at this point (e.g. a new state
        # but a stale details). Skip the publish rather than hand the worker an
        # inconsistent snapshot — it keeps pushing the last good one.
        mp_print(f"Failed to compose presence update: {e}")
        return
    worker = _get_worker()
    if worker is not None:
        worker.publish(MP_UPDATE_DETAILS)
