from __future__ import annotations


def display_unit(unit: str | None) -> str | None:
    """Convert common Wiren Board unit spellings to HA canonical units."""
    if unit is None:
        return None
    normalized = str(unit).strip()
    key = normalized.lower().replace("℉", "°f").replace("℃", "°c")
    aliases = {
        "deg c": "°C",
        "°c": "°C",
        "deg f": "°F",
        "°f": "°F",
        "%, rh": "%",
        "% rh": "%",
        "rh": "%",
        "m^3": "m³",
        "m3": "m³",
        "м^3": "m³",
        "м3": "m³",
    }
    return aliases.get(key, normalized)


def normalized_unit(unit: str | None) -> str | None:
    displayed = display_unit(unit)
    return displayed.lower() if displayed is not None else None
