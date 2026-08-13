from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import WBEntity
from .models import WBControl
from .sms import SMS_FIELDS, SmsAttemptTracker
from .sms_entity import WBSmsEntity
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    hidden = data.get("hidden_controls", set())
    inverted = data.get("inverted_binary_sensors", set())
    entities = [
        WBBinarySensor(client, control, control.key in inverted)
        for control in controls.values()
        if control.key not in hidden and _is_binary_sensor(control)
    ]
    entities.append(WBSmsScriptAvailable(entry, client))
    async_add_entities(entities)


def _is_binary_sensor(control: WBControl) -> bool:
    return (
        control.device_id != "sms_sender"
        and control.control_type == "switch"
        and control.is_readonly
    )


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


class WBSmsScriptAvailable(WBSmsEntity, BinarySensorEntity):
    _attr_translation_key = "sms_script_available"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, client: WBRuntimeClient) -> None:
        super().__init__(entry, client, "script_available")
        self._tracker = SmsAttemptTracker()

    async def async_added_to_hass(self) -> None:
        for field in SMS_FIELDS:
            self._client.subscribe_value(
                f"sms_sender/{field}",
                lambda value, current_field=field: self._handle_value(
                    current_field, value
                ),
            )

    @property
    def is_on(self) -> bool:
        return self._tracker.script_controls_available

    def _handle_value(self, field: str, value: str | None) -> None:
        self._tracker.update(field, value)
        self.async_write_ha_state()


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
