"""
GimpPresence settings dialog: rather than a custom GTK dialog, a procedure is registered 
which presents all settings options and writes to JSON on save, additionally interrupting 
the main (background) procedure's timer if the generalUpdate field was changed.

Originally AI-generated (Claude Opus 4.7); human-modified and reviewed.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import fields, Field
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Tuple, Type, get_type_hints

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, GLib, GObject, Gtk


SETTINGS_PROC_NAME = "gimppresence_open_settings"


# ---------------------------------------------------------------------------
# Naming: camelCase dataclass field <-> kebab-case GObject property
# ---------------------------------------------------------------------------

def field_to_property(name: str) -> str:
    """Convert camelCase property names to kebab-case."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name).lower()


def property_to_field(prop: str) -> str:
    """Convert kebab-case to camelCase."""
    parts = prop.split("-")
    if not parts:
        return prop
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# ---------------------------------------------------------------------------
# Atomic JSON write
# ---------------------------------------------------------------------------

def atomic_write_json(path: Path, data: dict) -> None:
    """Write `data` to `path` via tmp + rename so a crash mid-write can't
    leave a half-truncated file.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
        fp.flush()
        os.fsync(fp.fileno())  # durability — survives a power loss between write and rename
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Choice helpers
# ---------------------------------------------------------------------------

def _resolve_choices(settings_class: Type, choices_attr: str) -> List[Tuple[str, str]]:
    """From a `choices_attr` metadata value, return a list of (label, key) pairs.
      `choices_attr` should be a string name of a class attribute on settings_class 
      that is itself a list of (label, key) tuples.
    """
    choices = getattr(settings_class, choices_attr, None)
    if choices is None:
        raise AttributeError(
            f"choices_attr={choices_attr!r} doesn't exist on {settings_class.__name__}"
        )
    out: List[Tuple[str, str]] = []
    for item in choices:
        if len(item) == 2:
            out.append((str(item[0]), str(item[1])))
        else:
            raise ValueError(f"unsupported choice entry: {item!r}")
    return out


def _build_gimp_choice(label_key_pairs: Iterable[Tuple[str, str]]) -> "Gimp.Choice":
    """Construct a Gimp.Choice with stable weights (so the dialog renders
    options in declaration order, not alphabetical-by-label)."""
    choice = Gimp.Choice.new()
    for i, (label, key) in enumerate(label_key_pairs):
        # signature: choice.add(nick, weight, label, blurb)
        choice.add(key, i, label, "")
    return choice


# ---------------------------------------------------------------------------
# Argument registration
# ---------------------------------------------------------------------------

# Field names we never want to expose as procedure arguments (private state
# from JSONSharedSettings).
_PRIVATE_FIELD_NAMES = {"_path", "_warn", "_timer", "_loaded", "_app_name",
                        "_refresh_func", "_prev_interval"}


def _initial_default(settings_class: Type, f: Field) -> Any:
    """Pick the default the user sees on 'Reset to Factory Defaults'.

    Prefers _INITIAL_DEFAULTS (the GIMP-specific overrides) over the base
    dataclass field default."""
    initial = getattr(settings_class, "_INITIAL_DEFAULTS", {}) or {}
    return initial.get(f.name, f.default)


def _widget_kind(settings_class: Type, f: Field) -> str:
    """Mirror common.QtSettingsGUIMenu._widget_kind: explicit metadata wins;
    otherwise infer from the resolved Python type."""
    explicit = f.metadata.get("widget")
    if explicit:
        return explicit
    resolved = get_type_hints(settings_class)[f.name]
    return {bool: "checkbox", int: "spinbox", str: "lineedit"}.get(resolved, "lineedit")


def _blurb_for(f: Field) -> Optional[str]:
    """Long-form help text (becomes the tooltip in GIMP's dialog).

    Falls back to None — GIMP omits the tooltip in that case rather than
    showing an empty string."""
    blurb = f.metadata.get("blurb")
    return blurb if blurb else None


def _register_field(procedure: "Gimp.Procedure",
                    settings_class: Type,
                    f: Field) -> None:
    """Translate one dataclass field into the appropriate add_*_argument call."""
    prop_name = field_to_property(f.name)
    label = f.metadata.get("label") or f.name
    blurb = _blurb_for(f)
    default = _initial_default(settings_class, f)
    flags = GObject.ParamFlags.READWRITE

    kind = _widget_kind(settings_class, f)

    if kind == "checkbox":
        procedure.add_boolean_argument(prop_name, label, blurb, bool(default), flags)
    elif kind == "spinbox":
        lo = int(f.metadata.get("min", -10**9))
        hi = int(f.metadata.get("max", 10**9))
        procedure.add_int_argument(prop_name, label, blurb, lo, hi, int(default), flags)
    elif kind == "combobox":
        choices_attr = f.metadata.get("choices_attr")
        if choices_attr is None:
            raise ValueError(
                f"field {f.name!r} declares widget=combobox but no choices_attr"
            )
        pairs = _resolve_choices(settings_class, choices_attr)
        gimp_choice = _build_gimp_choice(pairs)
        default_key = str(default)
        # Make sure the default is actually one of the choices; GIMP will
        # raise if not.
        keys = {key for _, key in pairs}
        if default_key not in keys:
            default_key = pairs[0][1]
        procedure.add_choice_argument(prop_name, label, blurb, gimp_choice,
                                      default_key, flags)
    elif kind == "lineedit":
        procedure.add_string_argument(prop_name, label, blurb, str(default), flags)
    else:
        raise ValueError(f"unsupported widget kind {kind!r} for field {f.name!r}")


# ---------------------------------------------------------------------------
# Dialog assembly (groups + conditional sensitivity)
# ---------------------------------------------------------------------------

def _group_layout(settings_class: Type) -> List[Tuple[str, List[Field]]]:
    """Return [(group_name, [field, field, ...]), ...] preserving declaration
    order both within and between groups."""
    seen: List[str] = []
    by_group: dict[str, List[Field]] = {}
    for f in fields(settings_class):
        if f.name in _PRIVATE_FIELD_NAMES:
            continue
        g = f.metadata.get("group")
        if g is None:
            continue
        if g not in by_group:
            by_group[g] = []
            seen.append(g)
        by_group[g].append(f)
    return [(g, by_group[g]) for g in seen]


def _fill_dialog(dialog: "GimpUi.ProcedureDialog",
                 settings_class: Type) -> None:
    """Lay out the dialog using fill_frame for groups + per-field sensitivity
    sub-frames driven by metadata['group_master'] and metadata['controls'].

    The strategy:
      1. For each group, find the (zero or one) field with group_master=True.
         If present, the group becomes a fill_frame whose title is that bool
         and contents are the remaining fields.
      2. Within a group, any field with `controls=[...]` becomes a sub-frame
         whose title is that bool and contents are the listed fields.
      3. Fields not absorbed by (1) or (2) are appended in declaration order.
    """
    top_level_ids: List[str] = []

    for group_name, group_fields in _group_layout(settings_class):
        master: Optional[Field] = next(
            (f for f in group_fields if f.metadata.get("group_master")), None
        )

        # Collect leaf ids in this group, after splicing in any control-sub-frames.
        absorbed_by_controls: set[str] = set()
        leaf_ids: List[str] = []
        for f in group_fields:
            if master is not None and f.name == master.name:
                continue
            if f.name in absorbed_by_controls:
                continue
            controls = f.metadata.get("controls")
            if controls:
                sub_id = f"{field_to_property(f.name)}-frame"
                child_props = [field_to_property(c) for c in controls]
                dialog.fill_frame(
                    sub_id, field_to_property(f.name), False, child_props,
                )
                absorbed_by_controls.update(controls)
                leaf_ids.append(sub_id)
            else:
                leaf_ids.append(field_to_property(f.name))

        group_id = f"group-{field_to_property(group_name.replace(' ', '-'))}"
        if master is not None:
            # Frame's title is the master checkbox; sensitivity follows master.
            dialog.fill_frame(
                group_id, field_to_property(master.name), False, leaf_ids,
            )
        else:
            # No master — use a plain box for visual grouping with no
            # sensitivity logic.
            box = dialog.fill_box(group_id, leaf_ids)
            box.set_orientation(Gtk.Orientation.VERTICAL)
        top_level_ids.append(group_id)

    dialog.fill(top_level_ids)


# ---------------------------------------------------------------------------
# Run function factory
# ---------------------------------------------------------------------------

def _make_run_fn(settings_class: Type,
                 current_prefs: Any,
                 settings_json_path: Path,
                 on_settings_changed: Optional[Callable[[], None]],
                 plug_in_binary: str) -> Callable:
    """Returns a run function bound to the live in-memory settings object
    and the JSON path. The closure is what gets passed to Gimp.Procedure.new."""

    def run(procedure, config, run_data):  # pylint: disable=unused-argument
        # Seed the dialog with live values
        for f in fields(settings_class):
            if f.name in _PRIVATE_FIELD_NAMES or f.metadata.get("group") is None:
                continue
            prop = field_to_property(f.name)
            config.set_property(prop, getattr(current_prefs, f.name))
        GimpUi.init(plug_in_binary)
        dialog = GimpUi.ProcedureDialog.new(procedure, config,
                                            "GimpPresence Settings")
        try:
            _fill_dialog(dialog, settings_class)

            if not dialog.run():
                # User cancelled. GIMP discards the config changes; the
                # next dialog open shows the prior values.
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)

            # Dialog accepted. Read every property back and apply it to the
            # in-memory prefs, then persist to JSON.
            new_values: dict[str, Any] = {}
            for f in fields(settings_class):
                if f.name in _PRIVATE_FIELD_NAMES:
                    continue
                if f.metadata.get("group") is None:
                    continue
                prop = field_to_property(f.name)
                value = config.get_property(prop)
                new_values[f.name] = value
                # Mutate the live settings object so the background tick sees
                # the new values immediately. We bypass any custom __setattr__
                # write-back to disk by using object.__setattr__ — the JSON
                # write below is the single source of persistent truth.
                object.__setattr__(current_prefs, f.name, value)

            try:
                atomic_write_json(settings_json_path, new_values)
            except OSError as e:
                Gimp.warning(f"[GimpPresence] Failed to write new settings to JSON: {e}")
                # Don't fail the dialog — in-memory state was already updated.

            if on_settings_changed is not None:
                try:
                    on_settings_changed()
                except Exception as e:  # noqa: BLE001
                    Gimp.warning((
                        "[GimpPresence] failed to interrupt RPC timer; "
                        f"new settings may take time to take effect: {e}"
                    ))

            return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
        finally:
            dialog.destroy()

    return run


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_settings_procedure(
    plug_in: "Gimp.PlugIn",
    *,
    settings_class: Type,
    current_prefs: Any,
    settings_json_path: Path,
    on_settings_changed: Optional[Callable[[], None]] = None,
    proc_name: str = SETTINGS_PROC_NAME,
    plug_in_binary: str = "gimp-presence",
) -> "Gimp.Procedure":
    """Construct (but don't register) the temporary settings procedure.

    The caller is expected to register it once the persistent main loop is
    ready, via `plug_in.add_temp_procedure(returned_procedure)`, and to
    `plug_in.remove_temp_procedure(proc_name)` on shutdown.

    Args:
        plug_in: the parent Gimp.PlugIn (the persistent process).
        settings_class: dataclass type whose fields drive argument
            registration (GPSettings).
        current_prefs: the live, in-memory settings instance. Its fields are
            mutated in place when the dialog closes successfully.
        settings_json_path: pathlib.Path the dialog writes on success.
        on_settings_changed: optional callback fired after JSON write —
            typically calls timer.refresh() to pick up a new generalUpdate.
        proc_name: PDB procedure name (default: SETTINGS_PROC_NAME).
        plug_in_binary: identifier for GimpUi.init.

    Returns:
        Gimp.Procedure ready to hand to plug_in.add_temp_procedure(...).
    """
    run_fn = _make_run_fn(
        settings_class=settings_class,
        current_prefs=current_prefs,
        settings_json_path=settings_json_path,
        on_settings_changed=on_settings_changed,
        plug_in_binary=plug_in_binary,
    )

    procedure = Gimp.Procedure.new(
        plug_in,
        proc_name,
        Gimp.PDBProcType.TEMPORARY,
        run_fn,
        None,
    )

    procedure.set_menu_label("GimpPresence: Settings…")
    procedure.set_documentation(
        "Configure GimpPresence",
        "Open the GimpPresence settings dialog. Changes are applied to the "
        "running RPC client immediately on close and persisted to disk for "
        "future sessions.",
        None,
    )
    procedure.set_attribution("MarlArini", "MarlArini", "2026")
    procedure.add_menu_path("<Image>/Filters/Discord Presence/")

    for f in fields(settings_class):
        if f.name in _PRIVATE_FIELD_NAMES:
            continue
        if f.metadata.get("group") is None:
            continue
        _register_field(procedure, settings_class, f)

    return procedure
