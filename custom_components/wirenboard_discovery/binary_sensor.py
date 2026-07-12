from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    inverted = data.get("inverted_binary_sensors", set())
    async_add_entities(
        WBBinarySensor(client, control, control.key in inverted)
        for control in controls.values()
        if control.key not in hidden and _is_binary_sensor(control)
    )


def _is_binary_sensor(control: WBControl) -> bool:
    return control.control_type == "switch" and control.is_readonly


class WBBinarySensor(WBEntity, BinarySensorEntity):
    def __init__(self, client: WBRuntimeClient, control: WBControl, inverted: bool = False) -> None:
        super().__init__(client, control)
        self._inverted = inverted
        self._attr_device_class = _binary_device_class(control)

    @property
    def is_on(self) -> bool | None:
        if self._value is None:
            return None
        is_on = str(self._value).strip().lower() in {"1", "true", "on"}
        return not is_on if self._inverted else is_on


def _binary_device_class(control: WBControl) -> str | None:
    name = f"{control.control_id} {control.control_name or ''}".lower()
    if any(word in name for word in ("motion", "presence", "occupancy", "движ", "присутств")):
        return "motion"
    if any(word in name for word in ("leak", "water", "протеч")):
        return "moisture"
    if any(word in name for word in ("door", "window", "contact", "двер", "окн")):
        return "opening"
    if any(word in name for word in ("problem", "fault", "alarm", "авар", "ошиб", "тревог")):
        return "problem"
    if any(word in name for word in ("online", "connection", "доступ", "соедин")):
        return "connectivity"
    return None
