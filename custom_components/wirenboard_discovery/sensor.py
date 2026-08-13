from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity
from .models import WBControl, localized_title
from .sms import SMS_FIELDS
from .sms_entity import WBSmsEntity
from .units import display_unit, normalized_unit, numeric_state_class
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    hidden = data.get("hidden_controls", set())
    entities = [
        WBSensor(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_sensor(control)
    ]
    entities.extend(WBSmsDiagnosticSensor(entry, client, field) for field in SMS_FIELDS)
    async_add_entities(entities)


def _is_sensor(control: WBControl) -> bool:
    return (
        control.device_id != "sms_sender"
        and control.control_type not in {"switch", "range"}
        and control.is_readonly
    )


class WBSensor(WBEntity, SensorEntity):
    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        super().__init__(client, control)
        self._enum = {
            str(key): localized_title(title) or str(key)
            for key, title in (control.meta.get("enum") or {}).items()
        }
        metadata = _sensor_metadata(control)
        self._attr_device_class = metadata.get("device_class")
        self._attr_state_class = metadata.get("state_class")
        self._attr_native_unit_of_measurement = metadata.get("unit")

    @property
    def native_value(self):
        if self._value is None or str(self._value).strip() == "":
            return None
        if self._enum:
            return self._enum.get(str(self._value), str(self._value))
        try:
            return float(self._value)
        except ValueError:
            return self._value


class WBSmsDiagnosticSensor(WBSmsEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: ConfigEntry,
        client: WBRuntimeClient,
        field: str,
    ) -> None:
        super().__init__(entry, client, field)
        self._field = field
        self._value: str | None = None
        self._attr_translation_key = f"sms_{field}"
        if field == "last_sent_time":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    async def async_added_to_hass(self) -> None:
        self._client.subscribe_value(f"sms_sender/{self._field}", self._handle_value)

    @property
    def native_value(self):
        if not self._value:
            return None
        if self._field == "last_sent_time":
            try:
                return datetime.fromisoformat(self._value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if len(self._value) <= 250:
            return self._value
        return f"{self._value[:249]}…"

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if self._value and len(self._value) > 250:
            return {"full_value": self._value}
        return None

    def _handle_value(self, value: str | None) -> None:
        self._value = None if value is None else str(value).strip()
        self.async_write_ha_state()


def _sensor_metadata(control: WBControl) -> dict[str, str | None]:
    # Enum values are descriptive states, even when their parent logical group
    # is a gas/water meter. Giving them a numeric device class makes Home
    # Assistant try to parse localized labels such as "Хорошее" as numbers.
    if control.meta.get("enum"):
        return {"device_class": None, "unit": None, "state_class": None}

    control_type = (control.control_type or "").lower()
    configured_type = str(control.meta.get("ha_device_type") or "").lower()
    units = control.units or control.meta.get("units") or control.meta.get("unit")
    unit = display_unit(str(units)) if units is not None else None
    unit_key = normalized_unit(unit)
    text = f"{control.control_id} {control.control_name or ''}".lower()

    mapping = {
        "temperature": {"device_class": "temperature", "unit": unit or "°C"},
        "voltage": {"device_class": "voltage", "unit": unit or "V"},
        "rel_humidity": {"device_class": "humidity", "unit": unit or "%"},
        "humidity": {"device_class": "humidity", "unit": unit or "%"},
        "lux": {"device_class": "illuminance", "unit": unit or "lx"},
        "sound_level": {"device_class": "sound_pressure", "unit": unit or "dBA"},
        "power": {"device_class": "power", "unit": unit or "W"},
        "power_consumption": {"device_class": "energy", "unit": unit or "kWh"},
        "current": {"device_class": "current", "unit": unit or "A"},
        "frequency": {"device_class": "frequency", "unit": unit or "Hz"},
        "gas": {"device_class": "gas", "unit": unit or "m³"},
        "water": {"device_class": "water", "unit": unit or "m³"},
    }
    metadata = (
        mapping.get(configured_type)
        or mapping.get(control_type)
        or _metadata_from_unit(unit_key, unit, text)
        or {"device_class": None, "unit": unit}
    )
    # Unitless numeric channels (for example WB-MSW motion levels and modem
    # signal quality) are still measurements and may have recorder history.
    state_class = numeric_state_class(control.value, bool(control.meta.get("enum")))
    if metadata.get("device_class") in {"energy", "gas", "water"} and state_class:
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
        return {"device_class": "sound_pressure", "unit": unit or "dBA"}
    if unit_key in {"c", "°c"}:
        return {"device_class": "temperature", "unit": unit or "°C"}
    if unit_key == "%":
        if any(word in text for word in {"battery", "percentage", "батар", "заряд"}):
            return {"device_class": "battery", "unit": unit or "%"}
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
