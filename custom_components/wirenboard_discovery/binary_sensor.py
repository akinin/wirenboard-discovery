from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import CONF_MOTION_OFF_DELAY, CONF_MOTION_SETTINGS, CONF_MOTION_THRESHOLD, DOMAIN
from .entity import WBEntity
from .models import WBControl
from .motion import (
    DEFAULT_MOTION_OFF_DELAY,
    DEFAULT_MOTION_THRESHOLD,
    is_msw_max_motion,
    motion_level,
    motion_unique_id,
)
from .sms import SMS_FIELDS, SmsAttemptTracker
from .sms_entity import WBSmsEntity
from .standards import canonical_binary_device_class
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
        if not control.is_hidden and control.key not in hidden and _is_binary_sensor(control)
    ]
    motion_settings = entry.options.get(CONF_MOTION_SETTINGS, {})
    entities.extend(
        WBMotionSensor(client, control, motion_settings.get(control.device_id, {}))
        for control in controls.values()
        if control.key not in hidden and is_msw_max_motion(control)
    )
    entities.append(WBSmsScriptAvailable(entry, client))
    async_add_entities(entities)


def _is_binary_sensor(control: WBControl) -> bool:
    return (
        control.device_id != "sms_sender"
        and control.control_type in {"switch", "alarm"}
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


class WBMotionSensor(WBEntity, BinarySensorEntity):
    """Derive motion from the WB-MSW peak reading."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_is_on = None

    def __init__(
        self, client: WBRuntimeClient, control: WBControl, settings: dict[str, int]
    ) -> None:
        self._threshold = settings.get(CONF_MOTION_THRESHOLD, DEFAULT_MOTION_THRESHOLD)
        self._off_delay = settings.get(CONF_MOTION_OFF_DELAY, DEFAULT_MOTION_OFF_DELAY)
        self._level: float | None = None
        self._cancel_off: Callable[[], None] | None = None
        super().__init__(client, control)
        self._attr_unique_id = motion_unique_id(control.unique_id)
        self.entity_id = f"binary_sensor.{control.unique_id.removeprefix('wb_')}"

    def _control_name(self, control: WBControl) -> str:
        language = (self._client.language or "").replace("_", "-").split("-", 1)[0]
        return "Движение" if language == "ru" else "Motion"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._cancel_delayed_off)
        await super().async_added_to_hass()

    def _handle_value(self, value: str | None) -> None:
        previous = (self.available, self.is_on)
        self._level = motion_level(value)
        self._update_available()
        if previous != (self.available, self.is_on):
            self.async_write_ha_state()

    def _handle_connection(self, connected: bool) -> None:
        if not connected:
            self._level = None
        super()._handle_connection(connected)

    def _update_available(self) -> None:
        super()._update_available()
        if not self._attr_available or self._level is None:
            self._attr_available = False
            self._attr_is_on = None
            self._cancel_delayed_off()
        elif self._level >= self._threshold:
            self._attr_is_on = True
            self._cancel_delayed_off()
        elif not self._attr_is_on or not self._off_delay:
            self._attr_is_on = False
        elif self._cancel_off is None:
            self._cancel_off = async_call_later(self.hass, self._off_delay, self._finish_off)

    def _cancel_delayed_off(self) -> None:
        if self._cancel_off is not None:
            self._cancel_off()
            self._cancel_off = None

    @callback
    def _finish_off(self, _now: datetime) -> None:
        self._cancel_off = None
        self._attr_is_on = False
        self.async_write_ha_state()


class WBSmsScriptAvailable(WBSmsEntity, BinarySensorEntity):
    _attr_translation_key = "sms_script_available"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, client: WBRuntimeClient) -> None:
        super().__init__(entry, client, "script_available")
        self._tracker = SmsAttemptTracker()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for field in SMS_FIELDS:
            self.async_on_remove(
                self._client.subscribe_value(
                    f"sms_sender/{field}",
                    lambda value, current_field=field: self._handle_value(
                        current_field, value
                    ),
                )
            )

    @property
    def is_on(self) -> bool:
        return self._tracker.script_controls_available

    def _handle_value(self, field: str, value: str | None) -> None:
        self._tracker.update(field, value)
        self.async_write_ha_state()


def _binary_device_class(control: WBControl) -> str | None:
    standard_class = canonical_binary_device_class(control.control_id)
    if standard_class:
        return standard_class
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
