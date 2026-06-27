from __future__ import annotations

from homeassistant.components.number import NumberEntity
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
        WBNumber(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_number(control)
    )


def _is_number(control: WBControl) -> bool:
    return not control.is_readonly and (
        control.control_type == "range"
        or (control.control_type == "value" and _can_float(control.value))
    )


class WBNumber(WBEntity, NumberEntity):
    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        super().__init__(client, control)
        self._attr_device_class = control.ha_device_class or None
        self._attr_native_min_value = _float_meta(control, "min", 0)
        self._attr_native_max_value = _float_meta(control, "max", 100)
        self._attr_native_unit_of_measurement = control.units or control.meta.get("units") or control.meta.get("unit")

    @property
    def native_value(self) -> float | None:
        if self._value is None:
            return None
        try:
            return float(self._value)
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        self._client.publish_control(self._control, str(value))


def _float_meta(control: WBControl, key: str, default: float) -> float:
    try:
        return float(control.meta.get(key, default))
    except (TypeError, ValueError):
        return default


def _can_float(value: str | None) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
