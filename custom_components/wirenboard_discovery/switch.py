from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
        WBSwitch(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_switch(control)
    )


def _is_switch(control: WBControl) -> bool:
    return control.control_type == "switch" and not control.is_readonly


class WBSwitch(WBEntity, SwitchEntity):
    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        super().__init__(client, control)
        self._attr_device_class = control.ha_device_class or None

    @property
    def is_on(self) -> bool | None:
        if self._value is None:
            return None
        return str(self._value).strip().lower() in {"1", "true", "on"}

    async def async_turn_on(self, **kwargs) -> None:
        self._client.publish_control(self._control, "1")

    async def async_turn_off(self, **kwargs) -> None:
        self._client.publish_control(self._control, "0")
