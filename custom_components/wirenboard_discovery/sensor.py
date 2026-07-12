from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity
from .models import WBControl
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    hidden = data.get("hidden_controls", set())
    configured_classes = data.get("sensor_device_classes", {})
    async_add_entities(
        WBSensor(client, control, configured_classes.get(control.key))
        for control in controls.values()
        if control.key not in hidden and _is_sensor(control)
    )


def _is_sensor(control: WBControl) -> bool:
    return control.control_type not in {"switch", "range"} and control.is_readonly


class WBSensor(WBEntity, SensorEntity):
    def __init__(
        self, client: WBRuntimeClient, control: WBControl, configured_class: str | None = None
    ) -> None:
        super().__init__(client, control)
        metadata = _sensor_metadata(control)
        self._attr_device_class = configured_class or metadata.get("device_class")
        self._attr_state_class = metadata.get("state_class")
        self._attr_native_unit_of_measurement = metadata.get("unit")
        if configured_class in {"gas", "water"}:
            self._attr_state_class = "total_increasing"

    @property
    def native_value(self):
        if self._value is None:
            return None
        try:
            return float(self._value)
        except ValueError:
            return self._value


def _sensor_metadata(control: WBControl) -> dict[str, str | None]:
    control_type = (control.control_type or "").lower()
    units = control.units or control.meta.get("units") or control.meta.get("unit")
    unit = _display_unit(str(units)) if units is not None else None
    unit_key = _normalize_unit(unit)
    text = f"{control.control_id} {control.control_name or ''}".lower()

    mapping = {
        "temperature": {"device_class": "temperature", "unit": unit or "°C"},
        "voltage": {"device_class": "voltage", "unit": unit or "V"},
        "rel_humidity": {"device_class": "humidity", "unit": unit or "%"},
        "humidity": {"device_class": "humidity", "unit": unit or "%"},
        "lux": {"device_class": "illuminance", "unit": unit or "lx"},
        "sound_level": {"device_class": "sound_pressure", "unit": unit or "dB"},
        "power": {"device_class": "power", "unit": unit or "W"},
        "power_consumption": {"device_class": "energy", "unit": unit or "kWh"},
        "current": {"device_class": "current", "unit": unit or "A"},
        "frequency": {"device_class": "frequency", "unit": unit or "Hz"},
    }
    metadata = mapping.get(control_type) or _metadata_from_unit(unit_key, unit, text) or {"device_class": None, "unit": unit}
    state_class = "measurement" if _can_float(control.value) else None
    if metadata.get("device_class") == "energy" and state_class:
        state_class = "total_increasing"
    return {
        "device_class": metadata.get("device_class"),
        "unit": metadata.get("unit"),
        "state_class": state_class,
    }


def _metadata_from_unit(unit_key: str | None, unit: str | None, text: str) -> dict[str, str | None] | None:
    if unit_key in {"w", "kw"}:
        return {"device_class": "power", "unit": unit or "W"}
    if unit_key in {"v", "kv"}:
        return {"device_class": "voltage", "unit": unit or "V"}
    if unit_key in {"a", "ma"}:
        return {"device_class": "current", "unit": unit or "A"}
    if unit_key in {"wh", "kwh", "mwh"}:
        return {"device_class": "energy", "unit": unit or "kWh"}
    if unit_key in {"hz", "khz"}:
        return {"device_class": "frequency", "unit": unit or "Hz"}
    if unit_key in {"lx", "lux"}:
        return {"device_class": "illuminance", "unit": unit or "lx"}
    if unit_key in {"db", "dba"}:
        return {"device_class": "sound_pressure", "unit": unit or "dB"}
    if unit_key in {"c", "°c"}:
        return {"device_class": "temperature", "unit": unit or "°C"}
    if unit_key == "%":
        if any(word in text for word in {"humidity", "влажн"}):
            return {"device_class": "humidity", "unit": unit or "%"}
        if any(word in text for word in {"power factor", "cos", "pf", "коэффициент мощности"}):
            return {"device_class": "power_factor", "unit": unit or "%"}
        return {"device_class": None, "unit": unit or "%"}
    if unit_key in {"va", "kva"}:
        return {"device_class": "apparent_power", "unit": unit or "VA"}
    if unit_key in {"var", "kvar"}:
        return {"device_class": "reactive_power", "unit": unit or "var"}
    return None


def _normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return _display_unit(unit).strip().replace("℃", "°C").lower()


def _display_unit(unit: str) -> str:
    normalized = unit.strip()
    if normalized.lower() in {"m^3", "m3", "м^3", "м3"}:
        return "m³"
    return normalized


def _can_float(value: str | None) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
