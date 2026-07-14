from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity
from .models import WBControl, localized_title
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    hidden = data.get("hidden_controls", set())
    async_add_entities(
        WBSelect(client, control)
        for control in controls.values()
        if control.key not in hidden and _is_select(control)
    )


def _is_select(control: WBControl) -> bool:
    return not control.is_readonly and isinstance(control.meta.get("enum"), dict) and bool(control.meta["enum"])


class WBSelect(WBEntity, SelectEntity):
    def __init__(self, client: WBRuntimeClient, control: WBControl) -> None:
        super().__init__(client, control)
        enum = control.meta.get("enum", {})
        self._option_by_key = {
            str(key): localized_title(title) or str(key)
            for key, title in enum.items()
        }
        self._key_by_option = {option: key for key, option in self._option_by_key.items()}
        self._attr_options = list(self._key_by_option)

    @property
    def current_option(self) -> str | None:
        if self._value is None:
            return None
        return self._option_by_key.get(str(self._value), str(self._value))

    async def async_select_option(self, option: str) -> None:
        key = self._key_by_option.get(option)
        if key is None:
            raise ValueError(f"Unknown Wiren Board enum option: {option}")
        self._client.publish_control(self._control, key)
