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
    async_add_entities(
        WBSensor(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_sensor(control)
    )


def _is_sensor(control: WBControl) -> bool:
    return control.control_type not in {"switch", "range"} and control.is_readonly


class WBSensor(WBEntity, SensorEntity):
    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        super().__init__(client, control)
        metadata = _sensor_metadata(control)
        self._attr_device_class = metadata.get("device_class")
        self._attr_state_class = metadata.get("state_class")
        self._attr_native_unit_of_measurement = metadata.get("unit")

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
    unit = str(units) if units is not None else None

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
    metadata = mapping.get(control_type, {"device_class": None, "unit": unit})
    return {
        "device_class": metadata.get("device_class"),
        "unit": metadata.get("unit"),
        "state_class": "measurement" if _can_float(control.value) else None,
    }


def _can_float(value: str | None) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
