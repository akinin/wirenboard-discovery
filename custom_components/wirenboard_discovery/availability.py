from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .models import WBControl, has_meta_error
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
        self._controls = {
            control.key: control for control in controls if control is not None
        }
        self._control_errors = {
            key: has_meta_error(control.meta.get("error"))
            for key, control in self._controls.items()
        }
        self._device_errors = {
            control.device_id: False for control in self._controls.values()
        }
        self._connected = client.connected
        self._update(write_state=False)

    def subscribe(self) -> None:
        self._entity.async_on_remove(
            self._client.subscribe_connection(self._handle_connection)
        )
        for key in self._controls:
            self._entity.async_on_remove(
                self._client.subscribe_meta(key, self._handle_control_meta)
            )
        for device_id in self._device_errors:
            self._entity.async_on_remove(
                self._client.subscribe_device_meta(
                    device_id,
                    lambda meta, current_device=device_id: self._handle_device_meta(
                        current_device, meta
                    ),
                )
            )

    def _handle_connection(self, connected: bool) -> None:
        self._connected = connected
        self._update()

    def _handle_control_meta(self, control: WBControl) -> None:
        self._control_errors[control.key] = has_meta_error(control.meta.get("error"))
        self._update()

    def _handle_device_meta(self, device_id: str, meta: dict[str, object]) -> None:
        self._device_errors[device_id] = has_meta_error(meta.get("error"))
        self._update()

    def _update(self, write_state: bool = True) -> None:
        self._entity._attr_available = (
            self._connected
            and not any(self._control_errors.values())
            and not any(self._device_errors.values())
        )
        if write_state:
            self._entity.async_write_ha_state()
