from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity, platform_override
from .models import WBControl
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    hidden = data.get("hidden_controls", set())
    async_add_entities(
        WBButton(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_button(control)
    )


def _is_button(control: WBControl) -> bool:
    platform = platform_override(control)
    if platform is not None:
        return platform == "button"
    return control.control_type == "pushbutton" and not control.is_readonly


class WBButton(WBEntity, ButtonEntity):
    async def async_press(self) -> None:
        self._client.publish_control(self._control, "1")
