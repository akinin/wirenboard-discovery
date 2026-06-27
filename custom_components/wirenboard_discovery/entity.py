from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .models import WBControl
from .wb_mqtt import WBRuntimeClient

SWITCH_DEVICE_CLASS_PLATFORMS = {
    "fan": "fan",
    "light": "light",
    "lock": "lock",
    "siren": "siren",
    "valve": "valve",
}


class WBEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        self._client = client
        self._control = control
        self._value = control.value
        self._attr_unique_id = control.unique_id
        self._attr_name = control.ha_entity_name or control.control_name or control.control_id
        self._attr_icon = control.ha_icon or None
        device_identifier = control.ha_device_id or control.device_id
        device_name = control.ha_device_name or control.device_name or control.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            name=device_name,
            manufacturer="Wiren Board",
        )

    async def async_added_to_hass(self) -> None:
        self._client.subscribe_value(self._control.key, self._handle_value)

    def _handle_value(self, value: str | None) -> None:
        self._value = value
        self.async_write_ha_state()


def platform_for_control(control: WBControl) -> str | None:
    if control.control_type == "switch":
        if control.is_readonly:
            return "binary_sensor"
        device_class = (control.ha_device_class or "").strip()
        return SWITCH_DEVICE_CLASS_PLATFORMS.get(device_class, "switch")
    if control.control_type == "pushbutton" and not control.is_readonly:
        return "button"
    if control.control_type == "text" and not control.is_readonly:
        return "text"
    if not control.is_readonly and (
        control.control_type == "range"
        or (control.control_type == "value" and _can_float(control.value))
    ):
        return "number"
    if control.is_readonly:
        return "sensor"
    return None


def _can_float(value: str | None) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
