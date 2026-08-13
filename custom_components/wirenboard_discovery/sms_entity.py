from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .sms import SMS_DEVICE_ID, SMS_DEVICE_NAME
from .wb_mqtt import WBRuntimeClient


class WBSmsEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, client: WBRuntimeClient, key: str) -> None:
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_{SMS_DEVICE_ID}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{SMS_DEVICE_ID}")},
            name=SMS_DEVICE_NAME,
            manufacturer="Wiren Board",
            model="GSM modem",
        )
