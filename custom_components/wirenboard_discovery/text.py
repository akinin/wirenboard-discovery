from __future__ import annotations

from homeassistant.components.text import TextEntity
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
        WBText(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_text(control)
    )


def _is_text(control: WBControl) -> bool:
    return control.control_type == "text" and not control.is_readonly


class WBText(WBEntity, TextEntity):
    @property
    def native_value(self) -> str | None:
        return self._value

    async def async_set_value(self, value: str) -> None:
        self._client.publish_control(self._control, value)
