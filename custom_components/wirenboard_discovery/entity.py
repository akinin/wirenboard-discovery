from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .models import WBControl, has_meta_error, localized_title
from .wb_mqtt import WBRuntimeClient, identity_metadata_key


class WBEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        self._client = client
        self._control = control
        self._value = control.value
        self._connected = client.connected
        self._device_meta: dict[str, object] = dict(control.device_meta)
        self._attr_unique_id = control.unique_id
        self._attr_name = self._control_name(control)
        self._update_available()
        self._update_device_info()

    def _control_name(self, control: WBControl) -> str:
        return (
            localized_title(control.meta.get("title"), self._client.language)
            or localized_title(control.meta.get("name"), self._client.language)
            or control.control_name
            or control.control_id
        )

    def _update_device_info(self) -> None:
        control = self._control
        meta = {**self._control.device_meta, **self._device_meta}
        identity_key = identity_metadata_key(control.control_id)
        if identity_key and control.value is not None and str(control.value).strip():
            meta[identity_key] = control.value
        device_identifier = control.ha_device_id or control.device_id
        device_name = (
            control.ha_device_name
            or localized_title(meta.get("title"), self._client.language)
            or localized_title(meta.get("name"), self._client.language)
            or control.device_name
            or control.device_id
        )
        driver = _metadata_value(meta, "model", "device_type", "driver")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_identifier)},
            name=device_name,
            manufacturer=_manufacturer(control.device_id, meta),
            model=driver,
            sw_version=_metadata_value(meta, "fw", "firmware", "sw_version"),
            hw_version=_metadata_value(
                meta, "hw", "hardware", "hw_version", "hw_batch"
            ),
            serial_number=_metadata_value(meta, "sn", "serial", "serial_number"),
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
        # Device registry creation and async_added_to_hass happen in adjacent
        # platform steps. Persist retained identity metadata on the next loop
        # iteration, after the registry device is guaranteed to exist.
        self.hass.loop.call_soon(self._sync_device_registry_info)

    def _handle_value(self, value: str | None) -> None:
        identity_key = identity_metadata_key(self._control.control_id)
        if identity_key and (value is None or not str(value).strip()):
            self.async_write_ha_state()
            return
        self._value = value
        if identity_key:
            self._control.value = value
            self._update_device_info()
            self._sync_device_registry_info()
        self.async_write_ha_state()

    def _handle_meta(self, control: WBControl) -> None:
        self._control = control
        self._attr_name = self._control_name(control)
        self._update_device_info()
        self._sync_device_registry_info()
        self._update_available()
        self.async_write_ha_state()

    def _handle_device_meta(self, meta: dict[str, object]) -> None:
        self._device_meta = meta
        self._update_device_info()
        self._sync_device_registry_info()
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

    def _sync_device_registry_info(self) -> None:
        """Persist metadata that can arrive after the entity was registered."""
        if self.hass is None:
            return
        registry = dr.async_get(self.hass)
        identifier = self._control.ha_device_id or self._control.device_id
        device = registry.async_get_device(identifiers={(DOMAIN, identifier)})
        if device is None:
            return
        info = self._attr_device_info
        updates = {
            key: info.get(key)
            for key in (
                "manufacturer",
                "model",
                "sw_version",
                "hw_version",
                "serial_number",
            )
            if info.get(key) is not None
        }
        if updates:
            registry.async_update_device(device.id, **updates)


def _metadata_value(meta: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = meta.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _manufacturer(device_id: str, meta: dict[str, object]) -> str | None:
    explicit = _metadata_value(meta, "manufacturer", "vendor")
    if explicit:
        return explicit
    normalized = device_id.lower()
    if normalized.startswith("wb-"):
        return "Wiren Board"
    if normalized.startswith("meanwell-"):
        return "MEAN WELL"
    driver = str(meta.get("driver") or "").lower()
    if driver.startswith("wb-") and driver != "wb-modbus":
        return "Wiren Board"
    return None
