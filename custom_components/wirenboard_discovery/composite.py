from __future__ import annotations

from typing import Any

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .models import WBControl

TYPE_DEVICE = "device"
TYPE_COVER_GATE = "cover_gate"
TYPE_COVER = "cover"
TYPE_THERMOSTAT = "thermostat"
TYPE_AC = "ac"

COMPOSITE_TYPES = {TYPE_COVER_GATE, TYPE_COVER, TYPE_THERMOSTAT, TYPE_AC}
COVER_TYPES = {TYPE_COVER_GATE, TYPE_COVER}
CLIMATE_TYPES = {TYPE_THERMOSTAT, TYPE_AC}


def normalize_groups(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for group_id, group_value in groups.items():
        group = dict(group_value)
        group.setdefault("type", default_group_type(group_id, group))
        group.setdefault("icon", "")
        group.setdefault("roles", {})
        normalized[str(group_id)] = group
    return normalized


def default_group_type(group_id: str, group: dict[str, Any]) -> str:
    text = f"{group_id} {group.get('name') or ''} {' '.join(str(key) for key in group.get('controls', []))}".lower()
    if "ворот" in text or "gate" in text:
        return TYPE_COVER_GATE
    if "штор" in text or "роллет" in text or "cover" in text:
        return TYPE_COVER
    if "кондиц" in text or "ac" in text:
        return TYPE_AC
    if "термостат" in text or "thermostat" in text:
        return TYPE_THERMOSTAT
    return TYPE_DEVICE


def group_type(group: dict[str, Any]) -> str:
    return str(group.get("type") or TYPE_DEVICE)


def group_icon(group: dict[str, Any]) -> str | None:
    icon = group.get("icon")
    return str(icon) if icon else None


def group_roles(group: dict[str, Any]) -> dict[str, str]:
    roles = group.get("roles") or {}
    return {str(key): str(value) for key, value in roles.items() if value}


def composite_control_keys(groups: dict[str, dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for group in groups.values():
        if group_type(group) not in COMPOSITE_TYPES:
            continue
        keys.update(str(key) for key in group.get("controls", []))
        keys.difference_update(str(key) for key in group.get("expose_controls", []))
    return keys


def group_device_info(group_id: str, group: dict[str, Any]) -> DeviceInfo:
    name = str(group.get("name") or group_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"group:{group_id}")},
        name=name,
        manufacturer="Wiren Board",
    )


def control_by_role(
    group: dict[str, Any],
    controls: dict[str, WBControl],
    role: str,
    fallback: str | None = None,
) -> WBControl | None:
    roles = group_roles(group)
    key = roles.get(role)
    if key:
        return controls.get(key)
    if fallback:
        return _guess_control(group, controls, fallback)
    return None


def _guess_control(group: dict[str, Any], controls: dict[str, WBControl], role: str) -> WBControl | None:
    group_keys = [str(key) for key in group.get("controls", [])]
    candidates = [controls[key] for key in group_keys if key in controls]

    if role == "command":
        return _first(candidates, lambda control: not control.is_readonly and control.control_type in {"pushbutton", "switch"})
    if role == "position":
        return _first(candidates, lambda control: "position" in _control_text(control) or "позици" in _control_text(control))
    if role == "state":
        return _first(candidates, lambda control: any(word in _control_text(control) for word in ("status", "state", "состоя")))
    if role == "obstruction":
        return _first(candidates, lambda control: any(word in _control_text(control) for word in ("photo", "safety", "obstruction", "фото", "препят")))
    if role == "current_temperature":
        return _first(candidates, lambda control: control.control_type == "temperature" or "temperature" in _control_text(control))
    if role == "target_temperature":
        return _first(candidates, lambda control: not control.is_readonly and any(word in _control_text(control) for word in ("setpoint", "target", "задан")))
    if role == "power":
        return _first(candidates, lambda control: not control.is_readonly and any(word in _control_text(control) for word in ("power", "вкл", "on")))
    if role == "mode":
        return _first(candidates, lambda control: not control.is_readonly and "mode" in _control_text(control))
    if role == "fan":
        return _first(candidates, lambda control: not control.is_readonly and "fan" in _control_text(control))
    return None


def _first(candidates: list[WBControl], predicate) -> WBControl | None:
    for control in candidates:
        if predicate(control):
            return control
    return None


def _control_text(control: WBControl) -> str:
    return f"{control.control_id} {control.control_name or ''}".lower()
