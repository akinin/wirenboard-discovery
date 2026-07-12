from __future__ import annotations

import fnmatch
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .models import WBControl

_LOGGER = logging.getLogger(__name__)

GROUPS_FILE = "wirenboard_discovery.yaml"


def apply_device_groups(
    hass: HomeAssistant,
    controls: dict[str, WBControl],
    entry_groups: dict[str, dict[str, Any]] | None = None,
) -> None:
    config = _load_groups_config(hass)
    if entry_groups:
        config.update(entry_groups)
    if not config:
        return

    for group_id, group in config.items():
        name = group.get("name") or group_id
        device_type = str(group.get("type") or "device")
        patterns = group.get("controls") or []
        if isinstance(patterns, str):
            patterns = [patterns]
        for key, control in controls.items():
            if _matches_any(key, patterns):
                control.ha_device_id = f"group:{group_id}"
                control.ha_device_name = str(name)
                control.meta["ha_device_type"] = device_type


def _load_groups_config(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    path = hass.config.path(GROUPS_FILE)
    try:
        with open(path, encoding="utf-8") as file:
            raw = file.read()
    except FileNotFoundError:
        return {}
    except OSError:
        _LOGGER.exception("Cannot read %s", path)
        return {}

    try:
        import yaml

        parsed = yaml.safe_load(raw) or {}
    except Exception:
        _LOGGER.exception("Cannot parse %s", path)
        return {}

    groups = parsed.get("devices", parsed)
    if not isinstance(groups, dict):
        _LOGGER.warning("%s must contain a mapping of devices", GROUPS_FILE)
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for group_id, group in groups.items():
        if not isinstance(group, dict):
            _LOGGER.warning("Device group %s is not an object", group_id)
            continue
        normalized[str(group_id)] = group
    return normalized


def _matches_any(key: str, patterns: list[str]) -> bool:
    return any(key == pattern or fnmatch.fnmatchcase(key, pattern) for pattern in patterns)
