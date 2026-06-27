from __future__ import annotations

from homeassistant.components.light import LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity, platform_for_control
from .models import WBControl
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    hidden = data.get("hidden_controls", set())
    async_add_entities(
        WBLight(client, control)
        for control in controls.values()
        if control.key not in hidden and platform_for_control(control) == "light"
    )


class WBLight(WBEntity, LightEntity):
    @property
    def is_on(self) -> bool | None:
        return _is_on(self._value)

    async def async_turn_on(self, **kwargs) -> None:
        self._client.publish_control(self._control, "1")

    async def async_turn_off(self, **kwargs) -> None:
        self._client.publish_control(self._control, "0")


def _is_on(value: str | None) -> bool | None:
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "on"}
