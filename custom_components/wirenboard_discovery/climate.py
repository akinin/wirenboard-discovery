from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .composite import CLIMATE_TYPES, TYPE_AC, control_by_role, group_device_info, group_icon, group_type
from .const import DOMAIN
from .models import WBControl
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
        self._current_temperature_value = self._value(self._current_temperature)
        self._target_temperature_value = self._value(self._target_temperature)
        self._power_value = self._value(self._power)
        self._mode_value = self._value(self._mode)
        self._fan_value = self._value(self._fan)
        self._attr_name = str(group.get("name") or group_id)
        self._attr_unique_id = f"wb_group_{group_id}_climate"
        self._attr_device_info = group_device_info(group_id, group)
        self._attr_icon = group_icon(group)
        self._attr_supported_features = _climate_features(
            has_target=self._target_temperature is not None,
            has_fan=self._fan is not None,
        )
        self._attr_hvac_modes = _hvac_modes(group_type(group))

    async def async_added_to_hass(self) -> None:
        if self._current_temperature:
            self._client.subscribe_value(self._current_temperature.key, self._handle_current_temperature)
        if self._target_temperature:
            self._client.subscribe_value(self._target_temperature.key, self._handle_target_temperature)
        if self._power:
            self._client.subscribe_value(self._power.key, self._handle_power)
        if self._mode:
            self._client.subscribe_value(self._mode.key, self._handle_mode)
        if self._fan:
            self._client.subscribe_value(self._fan.key, self._handle_fan)

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
        mode = _normalize(self._mode_value)
        if mode in {"cool", "cooling", "холод", "охлаждение", "3"}:
            return _hvac("cool")
        if mode in {"heat", "heating", "тепло", "нагрев", "4"}:
            return _hvac("heat")
        if mode in {"dry", "осушение", "2"}:
            return _hvac("dry")
        if mode in {"fan", "fan_only", "вентиляция", "1"}:
            return _hvac("fan_only")
        if group_type(self._group) == TYPE_AC:
            return _hvac("cool")
        return _hvac("heat")

    @property
    def fan_mode(self) -> str | None:
        return self._fan_value

    async def async_set_temperature(self, **kwargs) -> None:
        if self._target_temperature is None or "temperature" not in kwargs:
            return
        self._client.publish_control(self._target_temperature, str(kwargs["temperature"]))

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        mode = str(hvac_mode)
        if mode.endswith(".OFF") or mode == "off":
            if self._power is not None:
                self._client.publish_control(self._power, "0")
            return
        if self._power is not None:
            self._client.publish_control(self._power, "1")
        if self._mode is not None:
            commands = self._group.get("commands") or {}
            self._client.publish_control(self._mode, str(commands.get(mode, mode)))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if self._fan is not None:
            self._client.publish_control(self._fan, fan_mode)

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


def _hvac_modes(device_type: str) -> list:
    if device_type == TYPE_AC:
        modes = ["off", "cool", "heat", "dry", "fan_only"]
    else:
        modes = ["off", "heat"]
    return [_hvac(mode) for mode in modes]


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
