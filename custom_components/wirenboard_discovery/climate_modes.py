from __future__ import annotations

from collections.abc import Mapping


_MODE_ALIASES = {
    "cool": ("cool", "cooling", "холод", "охлажд"),
    "heat": ("heat", "heating", "тепло", "нагрев", "обогрев"),
    "dry": ("dry", "осуш"),
    "fan_only": ("fan", "ventilation", "вентил"),
}

_LEGACY_NUMERIC_MODES = {
    "1": "fan_only",
    "2": "dry",
    "3": "cool",
    "4": "heat",
}


def is_primary_mode_control(control_id: str, control_name: str | None) -> bool:
    """Return whether a control is the device's primary mode control."""
    return any(
        _normalize(value) in {"mode", "режим"}
        for value in (control_id, control_name)
        if value
    )


def resolve_hvac_mode(
    value: str | None,
    options: Mapping[str, str],
    *,
    default: str,
) -> str:
    """Resolve a device mode value to a Home Assistant HVAC mode."""
    key = str(value or "")
    if key in options:
        return _mode_name_to_hvac(options[key]) or default
    return _mode_name_to_hvac(key, allow_legacy_numeric=True) or default


def available_hvac_modes(
    device_type: str, options: Mapping[str, str]
) -> list[str]:
    """Return all HVAC modes represented by the device enum."""
    defaults = ["cool", "heat", "dry", "fan_only"] if device_type == "ac" else ["heat"]
    represented = {
        mode
        for label in options.values()
        if (mode := _mode_name_to_hvac(label)) is not None
    }
    modes = ["off"]
    for mode in defaults:
        if not options or mode in represented:
            modes.append(mode)
    for mode in ("cool", "heat", "dry", "fan_only"):
        if mode in represented and mode not in modes:
            modes.append(mode)
    return modes


def enum_key_for_hvac_mode(
    hvac_mode: str, options: Mapping[str, str]
) -> str | None:
    """Return the device enum key corresponding to an HVAC mode."""
    normalized_mode = normalize_hvac_mode(hvac_mode)
    return next(
        (
            key
            for key, label in options.items()
            if _mode_name_to_hvac(label) == normalized_mode
        ),
        None,
    )


def normalize_hvac_mode(value: object) -> str:
    """Normalize an HVACMode enum or string to its Home Assistant value."""
    normalized = _normalize(str(value))
    return normalized.rsplit(".", 1)[-1]


def _mode_name_to_hvac(
    value: str | None, *, allow_legacy_numeric: bool = False
) -> str | None:
    normalized = _normalize(value)
    if allow_legacy_numeric and normalized in _LEGACY_NUMERIC_MODES:
        return _LEGACY_NUMERIC_MODES[normalized]
    for hvac_mode, aliases in _MODE_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return hvac_mode
    return None


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()
