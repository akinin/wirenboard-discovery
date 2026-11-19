from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .models import WBControl
from .wb_mqtt import WBRuntimeClient


class WBAvailabilityTracker:
    """Track broker, device and control availability for a composite entity."""

    def __init__(
        self,
        entity: Entity,
        client: WBRuntimeClient,
        controls: list[WBControl | None],
    ) -> None:
        self._entity = entity
        self._client = client
        self._control_keys = {control.key for control in controls if control is not None}
        self._device_ids = {control.device_id for control in controls if control is not None}
        self._connected = client.connected
        self._update(write_state=False)

    def subscribe(self) -> None:
        self._entity.async_on_remove(
            self._client.subscribe_connection(self._handle_connection)
        )
        for key in self._control_keys:
            self._entity.async_on_remove(
                self._client.subscribe_meta(key, self._handle_metadata)
            )
        for device_id in self._device_ids:
            self._entity.async_on_remove(
                self._client.subscribe_device_meta(device_id, self._handle_metadata)
            )

    def _handle_connection(self, connected: bool) -> None:
        self._connected = connected
        self._update()

    def _handle_metadata(self, _metadata: WBControl | dict[str, object]) -> None:
        self._update()

    def _update(self, write_state: bool = True) -> None:
        self._entity._attr_available = self._connected and all(
            self._client.control_available(key) for key in self._control_keys
        )
        if write_state:
            self._entity.async_write_ha_state()
