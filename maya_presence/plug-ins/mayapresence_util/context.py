"""Scene information retrieval class for MayaPresence."""
import os
from pathlib import Path
from typing import cast, List, Tuple

import maya.cmds as cmds  # pyright: ignore[reportMissingImports] pylint: disable=import-error

from common import plural as mp_plural, shorten_number, get_file_size_str

from .shared_state import MP_PREFS
from . import extension_types

class MPContext:
    @classmethod
    def capture(cls) -> "MPContext | None":
        return cls()

    def get_gpu_str(self) -> str:
        try:
            card = cmds.openGLExtension(renderer=True) or ""
            if card:
                if "NVIDIA GeForce " in card:
                    card = card.replace("NVIDIA GeForce ", "")
                if "Radeon " in card:
                    card = card.replace("Radeon ", "")
                slash_loc = card.find("/")
                if slash_loc != -1:
                    return card[: card.find("/")]
                return card
            return ""
        except RuntimeError:
            return ""

    def get_project_name(self) -> str:
        return cast(str, cmds.workspace(query=True, shortName=True))

    def get_file_name(self, ext: bool = False) -> str:
        """
        Return the file name of the scene, if it is saved.
        `ext` determines whether to include the .mb extension
        """
        p = cast(str, cmds.file(query=True, sceneName=True))
        if p:
            return Path(p).name if ext else Path(p).stem
        return ""

    def get_current_scene(self) -> str:
        project_name = self.get_project_name()
        file_name = self.get_file_name()
        fallback_name = "Untitled Scene"
        if project_name and file_name:
            return project_name + " | " + file_name
        elif project_name:
            return project_name
        elif file_name:
            return file_name
        return fallback_name

    def get_cam_count(self) -> str:
        cams = len(cmds.ls(cameras=True)) - 4  # persp,top,front,side
        return mp_plural(cams, "camera")

    def get_light_count(self) -> str:
        lights = cmds.ls(lights=True) or []
        if MP_PREFS.countExtensions and extension_types.MP_EXT_LIGHTS:
            ext_lights = cmds.ls(type=list(extension_types.MP_EXT_LIGHTS)) or []
            lights = list(set(lights) | set(ext_lights))
        return mp_plural(len(lights), "light")

    def get_mesh_count(self) -> str:
        meshes = cmds.ls(geometry=True, visible=True, noIntermediate=True, type="mesh")
        return mp_plural(len(meshes), "mesh", "es")

    def get_poly_count_str(self) -> str:
        # Ideal: HUD Poly Count enabled (includes smoothing)
        if cmds.headsUpDisplay("HUDPolyCountVerts", query=True, visible=True) == 1:
            verts = cast(
                List[int],
                cmds.headsUpDisplay("HUDPolyCountVerts", query=True, scriptResult=True),
            )[0]
            faces = cast(
                List[int],
                cmds.headsUpDisplay("HUDPolyCountFaces", query=True, scriptResult=True),
            )[0]
        # Fallback: raw values
        else:
            meshes = cmds.ls(type="mesh", visible=True)
            polys = cmds.polyEvaluate(meshes, vertex=True, face=True)  # type: ignore[arg-type]
            if isinstance(polys, str):
                verts, faces = 0, 0  # polyEvaluate with no selection returns a string
            else:
                verts = polys["vertex"]
                faces = polys["face"]
        try:
            vert_str = "vert" if int(verts) == 1 else "verts"
            verts = shorten_number(int(verts))
            face_str = "face" if int(faces) == 1 else "faces"
            faces = shorten_number(int(faces))
            return f"{verts} {vert_str} | {faces} {face_str}"
        except (
            ValueError
        ):  # For some reason during startup verts is occasionally a string
            return "Unknown polygon count"

    def get_joint_count(self) -> str:
        joints = len(cmds.ls(type="joint"))
        return mp_plural(joints, "joint")

    def get_blendshape_count(self) -> str:
        blendshapes = len(cmds.ls(type="blendShape"))
        return mp_plural(blendshapes, "blendshape")

    def get_mat_count(self) -> str:
        mats = cmds.ls(materials=True) or []
        if MP_PREFS.countExtensions and extension_types.MP_EXT_MATERIALS:
            ext_mats = cmds.ls(type=list(extension_types.MP_EXT_MATERIALS)) or []
            mats = list(set(mats) | set(ext_mats))
        return mp_plural(len(mats), "material")

    def get_tex_count(self) -> str:
        textures = cmds.ls(textures=True) or []
        if MP_PREFS.countExtensions and extension_types.MP_EXT_TEXTURES:
            ext_textures = cmds.ls(type=list(extension_types.MP_EXT_TEXTURES)) or []
            textures = list(set(textures) | set(ext_textures))
        return mp_plural(len(textures), "texture")

    def get_file_size(self) -> str | None:
        p = cast(str, cmds.file(query=True, sceneName=True))
        if p and os.path.exists(p):
            return get_file_size_str(os.path.getsize(p))
        return None

    def get_version_str(self) -> str:
        try:
            major = cmds.about(majorVersion=True)
            minor = cmds.about(minorVersion=True)
            patch = cmds.about(patchVersion=True)
            return f"{major}.{minor}.{patch}"
        except Exception:
            return cmds.about(version=True)

    def get_render_engine_str(self) -> str:
        try:
            i = cmds.getAttr("defaultRenderGlobals.currentRenderer") or ""
        except RuntimeError:
            return "Unknown"
        mp_render_map = {
            "arnold": "Arnold",
            "redshift": "Redshift",
            "renderman": "RenderMan",
            "renderManRIS": "RenderMan",
            "vray": "V-Ray",
            "OctaneRender": "Octane",
            "mayaSoftware": "Maya Software",
            "mayaHardware2": "Maya Hardware 2.0",
        }
        if i in mp_render_map:
            return mp_render_map[i]
        return i if i else "Unknown"

    def get_active_object(self) -> str | None:
        sel = cmds.ls(selection=True) or []
        return sel[0] if sel else None

    def get_render_resolution(self) -> Tuple[int, int] | None:
        try:
            return (
                cmds.getAttr("defaultResolution.width"),
                cmds.getAttr("defaultResolution.height"),
            )
        except RuntimeError:
            return None

    def get_fps(self) -> int | None:
        try:
            u = cast(str, cmds.currentUnit(query=True, time=True)) or ""
        except RuntimeError:
            return 24
        presets = {"game": 15, "film": 24, "pal": 25, "ntsc": 30,
                   "show": 48, "palf": 50, "ntscf": 60}  # fmt: skip
        if u in presets:
            return presets[u]
        if u.endswith("fps"):
            try:
                return int(round(float(u[:-3])))
            except ValueError:
                return None
        return 24

    def get_current_frame(self) -> str:
        fps = self.get_fps()
        return f"Frame {int(cmds.currentTime(query=True))} ({fps}fps)"

    def get_user_context(self) -> str | None:
        current_ctx = cmds.currentCtx()
        if current_ctx.endswith("Ctx"):
            current_ctx = current_ctx[:-3]
        elif current_ctx.endswith("Context"):
            current_ctx = current_ctx[:-7]
        if not current_ctx:
            return None
        return f"Context: {current_ctx[0].upper()}{current_ctx[1:]}"
