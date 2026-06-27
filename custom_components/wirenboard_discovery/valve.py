from __future__ import annotations

from homeassistant.components.valve import ValveEntity
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
        WBValve(client, control)
        for control in controls.values()
        if control.key not in hidden and platform_for_control(control) == "valve"
    )


class WBValve(WBEntity, ValveEntity):
    @property
    def is_closed(self) -> bool | None:
        is_open = _is_on(self._value)
        if is_open is None:
            return None
        return not is_open

    async def async_open_valve(self, **kwargs) -> None:
        self._client.publish_control(self._control, "1")

    async def async_close_valve(self, **kwargs) -> None:
        self._client.publish_control(self._control, "0")


def _is_on(value: str | None) -> bool | None:
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "on"}
