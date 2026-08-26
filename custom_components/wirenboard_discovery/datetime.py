from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity
from .models import WBControl
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
        WBDateTime(client, control)
        for control in controls.values()
        if not control.is_hidden
        and control.key not in hidden
        and _is_datetime(control)
    )


def _is_datetime(control: WBControl) -> bool:
    return control.control_type == "unixtime" and not control.is_readonly


class WBDateTime(WBEntity, DateTimeEntity):
    @property
    def native_value(self) -> datetime | None:
        if self._value is None:
            return None
        try:
            return datetime.fromtimestamp(float(self._value), tz=timezone.utc)
        except (OverflowError, TypeError, ValueError):
            return None

    async def async_set_value(self, value: datetime) -> None:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        self._client.publish_control(self._control, str(round(value.timestamp())))
