from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .models import WBControl, has_meta_error
from .wb_mqtt import WBRuntimeClient


class WBEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        self._client = client
        self._control = control
        self._value = control.value
        self._connected = client.connected
        self._device_meta: dict[str, object] = {}
        self._attr_unique_id = control.unique_id
        self._attr_name = control.control_name or control.control_id
        self._update_available()
        device_identifier = control.ha_device_id or control.device_id
        device_name = control.ha_device_name or control.device_name or control.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            name=device_name,
            manufacturer="Wiren Board",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._client.subscribe_value(self._control.key, self._handle_value)
        )
        self.async_on_remove(
            self._client.subscribe_meta(self._control.key, self._handle_meta)
        )
        self.async_on_remove(
            self._client.subscribe_device_meta(
                self._control.device_id, self._handle_device_meta
            )
        )
        self.async_on_remove(
            self._client.subscribe_connection(self._handle_connection)
        )

    def _handle_value(self, value: str | None) -> None:
        self._value = value
        self.async_write_ha_state()

    def _handle_meta(self, control: WBControl) -> None:
        self._control = control
        self._update_available()
        self.async_write_ha_state()

    def _handle_device_meta(self, meta: dict[str, object]) -> None:
        self._device_meta = meta
        self._update_available()
        self.async_write_ha_state()

    def _handle_connection(self, connected: bool) -> None:
        self._connected = connected
        self._update_available()
        self.async_write_ha_state()

    def _update_available(self) -> None:
        self._attr_available = (
            self._connected
            and not has_meta_error(self._control.meta.get("error"))
            and not has_meta_error(self._device_meta.get("error"))
        )
