from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .models import WBControl
from .wb_mqtt import WBRuntimeClient


class WBEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        self._client = client
        self._control = control
        self._value = control.value
        self._attr_unique_id = control.unique_id
        self._attr_name = control.control_name or control.control_id
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
