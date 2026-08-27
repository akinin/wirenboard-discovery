from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .availability import WBAvailabilityTracker
from .climate_modes import (
    available_hvac_modes,
    enum_key_for_hvac_mode,
    normalize_hvac_mode,
    resolve_hvac_mode,
)
from .composite import CLIMATE_TYPES, TYPE_AC, control_by_role, group_device_info, group_icon, group_type
from .const import DOMAIN
from .models import WBControl, localized_title
from .wb_mqtt import WBRuntimeClient

try:
    from homeassistant.components.climate import ClimateEntityFeature
    from homeassistant.components.climate.const import HVACMode
except ImportError:  # pragma: no cover - compatibility with older Home Assistant
    ClimateEntityFeature = None
    HVACMode = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    groups = data.get("groups", {})
    entities = []
    for group_id, group in groups.items():
        if group_type(group) in CLIMATE_TYPES:
            entities.append(WBClimate(client, controls, group_id, group))
    async_add_entities(entities)


class WBClimate(ClimateEntity):
    _attr_has_entity_name = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        client: WBRuntimeClient,
        controls: dict[str, WBControl],
        group_id: str,
        group: dict,
    ) -> None:
        self._client = client
        self._group = group
        self._current_temperature = control_by_role(group, controls, "current_temperature", "current_temperature")
        self._target_temperature = control_by_role(group, controls, "target_temperature", "target_temperature")
        self._power = control_by_role(group, controls, "power", "power")
        self._mode = control_by_role(group, controls, "mode", "mode")
        self._fan = control_by_role(group, controls, "fan", "fan")
        self._availability = WBAvailabilityTracker(
            self,
            client,
            [
                self._current_temperature,
                self._target_temperature,
                self._power,
                self._mode,
                self._fan,
            ],
        )
        self._current_temperature_value = self._value(self._current_temperature)
        self._target_temperature_value = self._value(self._target_temperature)
        self._power_value = self._value(self._power)
        self._mode_value = self._value(self._mode)
        self._fan_value = self._value(self._fan)
        self._mode_option_by_key = _enum_options(self._mode, client.language)
        self._fan_option_by_key = _enum_options(self._fan, client.language)
        self._fan_key_by_option = {
            option: key for key, option in self._fan_option_by_key.items()
        }
        self._attr_name = str(group.get("name") or group_id)
        self._attr_unique_id = f"wb_group_{group_id}_climate"
        self._attr_device_info = group_device_info(group_id, group)
        self._attr_icon = group_icon(group)
        self._attr_supported_features = _climate_features(
            has_target=self._target_temperature is not None,
            has_fan=bool(self._fan_option_by_key),
        )
        self._attr_hvac_modes = [
            _hvac(mode)
            for mode in available_hvac_modes(
                group_type(group), self._mode_option_by_key
            )
        ]
        self._attr_fan_modes = list(self._fan_key_by_option) or None

    async def async_added_to_hass(self) -> None:
        self._availability.subscribe()
        if self._current_temperature:
            self.async_on_remove(
                self._client.subscribe_value(
                    self._current_temperature.key,
                    self._handle_current_temperature,
                )
            )
        if self._target_temperature:
            self.async_on_remove(
                self._client.subscribe_value(
                    self._target_temperature.key,
                    self._handle_target_temperature,
                )
            )
        if self._power:
            self.async_on_remove(
                self._client.subscribe_value(self._power.key, self._handle_power)
            )
        if self._mode:
            self.async_on_remove(
                self._client.subscribe_value(self._mode.key, self._handle_mode)
            )
        if self._fan:
            self.async_on_remove(
                self._client.subscribe_value(self._fan.key, self._handle_fan)
            )

    @property
    def current_temperature(self) -> float | None:
        return _float(self._current_temperature_value)

    @property
    def target_temperature(self) -> float | None:
        return _float(self._target_temperature_value)

    @property
    def hvac_mode(self):
        if self._power is not None and _normalize(self._power_value) in {"0", "false", "off"}:
            return _hvac("off")
        return _hvac(
            resolve_hvac_mode(
                self._mode_value,
                self._mode_option_by_key,
                default="cool" if group_type(self._group) == TYPE_AC else "heat",
            )
        )

    @property
    def fan_mode(self) -> str | None:
        if self._fan_value is None:
            return None
        return self._fan_option_by_key.get(
            str(self._fan_value), str(self._fan_value)
        )

    async def async_set_temperature(self, **kwargs) -> None:
        if self._target_temperature is None or "temperature" not in kwargs:
            return
        self._client.publish_control(self._target_temperature, str(kwargs["temperature"]))

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        mode = normalize_hvac_mode(hvac_mode)
        if mode == "off":
            if self._power is not None:
                self._client.publish_control(self._power, "0")
            return
        if self._power is not None:
            self._client.publish_control(self._power, "1")
        if self._mode is not None and not self._mode.is_readonly:
            commands = self._group.get("commands") or {}
            command = commands.get(mode)
            if command is None:
                command = enum_key_for_hvac_mode(mode, self._mode_option_by_key)
            self._client.publish_control(self._mode, str(command or mode))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if self._fan is not None:
            key = self._fan_key_by_option.get(fan_mode)
            if key is None:
                raise ValueError(f"Unknown Wiren Board fan mode: {fan_mode}")
            self._client.publish_control(self._fan, key)

    def _handle_current_temperature(self, value: str | None) -> None:
        self._current_temperature_value = value
        self.async_write_ha_state()

    def _handle_target_temperature(self, value: str | None) -> None:
        self._target_temperature_value = value
        self.async_write_ha_state()

    def _handle_power(self, value: str | None) -> None:
        self._power_value = value
        self.async_write_ha_state()

    def _handle_mode(self, value: str | None) -> None:
        self._mode_value = value
        self.async_write_ha_state()

    def _handle_fan(self, value: str | None) -> None:
        self._fan_value = value
        self.async_write_ha_state()

    @staticmethod
    def _value(control: WBControl | None) -> str | None:
        return control.value if control else None


def _climate_features(has_target: bool, has_fan: bool) -> int:
    if ClimateEntityFeature is None:
        features = 0
        if has_target:
            features |= 1
        if has_fan:
            features |= 8
        return features
    features = ClimateEntityFeature(0)
    if has_target:
        features |= ClimateEntityFeature.TARGET_TEMPERATURE
    if has_fan:
        features |= ClimateEntityFeature.FAN_MODE
    return features


def _hvac(mode: str):
    if HVACMode is None:
        return mode
    return getattr(HVACMode, mode.upper())


def _float(value: str | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()


def _enum_options(
    control: WBControl | None, language: str | None = None
) -> dict[str, str]:
    if control is None or not isinstance(control.meta.get("enum"), dict):
        return {}
    return {
        str(key): localized_title(title, language) or str(key)
        for key, title in control.meta["enum"].items()
    }
