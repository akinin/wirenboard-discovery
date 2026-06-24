from __future__ import annotations

from homeassistant.components.cover import CoverEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .composite import COVER_TYPES, control_by_role, group_device_info, group_icon, group_type
from .const import DOMAIN
from .models import WBControl
from .wb_mqtt import WBRuntimeClient

try:
    from homeassistant.components.cover import CoverDeviceClass, CoverEntityFeature
except ImportError:  # pragma: no cover - compatibility with older Home Assistant
    CoverDeviceClass = None
    CoverEntityFeature = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client = data["client"]
    controls = data["controls"]
    groups = data.get("groups", {})
    entities = []
    for group_id, group in groups.items():
        if group_type(group) in COVER_TYPES:
            entities.append(WBCover(client, controls, group_id, group))
    async_add_entities(entities)


class WBCover(CoverEntity):
    _attr_has_entity_name = False

    def __init__(
        self,
        client: WBRuntimeClient,
        controls: dict[str, WBControl],
        group_id: str,
        group: dict,
    ) -> None:
        self._client = client
        self._controls = controls
        self._group_id = group_id
        self._group = group
        self._command = control_by_role(group, controls, "command", "command")
        self._position = control_by_role(group, controls, "position", "position")
        self._state = control_by_role(group, controls, "state", "state")
        self._obstruction = control_by_role(group, controls, "obstruction", "obstruction")
        self._state_value = self._state.value if self._state else None
        self._position_value = self._position.value if self._position else None
        self._obstruction_value = self._obstruction.value if self._obstruction else None
        self._attr_name = str(group.get("name") or group_id)
        self._attr_unique_id = f"wb_group_{group_id}_cover"
        self._attr_device_info = group_device_info(group_id, group)
        self._attr_icon = group_icon(group)
        self._attr_device_class = _cover_device_class(group)
        self._attr_supported_features = _cover_features(self._command is not None, self._position is not None)

    async def async_added_to_hass(self) -> None:
        if self._state:
            self._client.subscribe_value(self._state.key, self._handle_state)
        if self._position:
            self._client.subscribe_value(self._position.key, self._handle_position)
        if self._obstruction:
            self._client.subscribe_value(self._obstruction.key, self._handle_obstruction)

    @property
    def current_cover_position(self) -> int | None:
        if self._position_value is None:
            return None
        try:
            return max(0, min(100, int(float(self._position_value))))
        except ValueError:
            return None

    @property
    def is_closed(self) -> bool | None:
        text = _normalize(self._state_value)
        if text in {"closed", "close", "закрыто", "закрыт", "0"}:
            return True
        if text in {"open", "opened", "открыто", "открыт", "1"}:
            return False
        position = self.current_cover_position
        if position is not None:
            return position == 0
        return None

    @property
    def is_opening(self) -> bool:
        return _normalize(self._state_value) in {"opening", "открывается"}

    @property
    def is_closing(self) -> bool:
        return _normalize(self._state_value) in {"closing", "закрывается"}

    @property
    def is_blocked(self) -> bool | None:
        if self._obstruction_value is None:
            return None
        return _normalize(self._obstruction_value) in {"1", "true", "on", "open", "opened"}

    async def async_open_cover(self, **kwargs) -> None:
        self._publish_command("open")

    async def async_close_cover(self, **kwargs) -> None:
        self._publish_command("close")

    async def async_stop_cover(self, **kwargs) -> None:
        self._publish_command("stop")

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs.get("position")
        if position is None:
            return
        target = control_by_role(self._group, self._controls, "target_position")
        if target is not None:
            self._client.publish_control(target, str(position))
            return
        self._publish_command(str(position))

    def _publish_command(self, action: str) -> None:
        if self._command is None:
            return
        roles = self._group.get("commands") or {}
        payload = str(roles.get(action, "1"))
        self._client.publish_control(self._command, payload)

    def _handle_state(self, value: str | None) -> None:
        self._state_value = value
        self.async_write_ha_state()

    def _handle_position(self, value: str | None) -> None:
        self._position_value = value
        self.async_write_ha_state()

    def _handle_obstruction(self, value: str | None) -> None:
        self._obstruction_value = value
        self.async_write_ha_state()


def _cover_device_class(group: dict):
    device_type = group_type(group)
    if CoverDeviceClass is None:
        return "gate" if device_type == "cover_gate" else None
    if device_type == "cover_gate":
        return CoverDeviceClass.GATE
    return None


def _cover_features(has_command: bool, has_position: bool) -> int:
    if CoverEntityFeature is None:
        features = 0
        if has_command:
            features |= 1 | 2 | 8
        if has_position:
            features |= 4
        return features

    features = CoverEntityFeature(0)
    if has_command:
        features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    if has_position:
        features |= CoverEntityFeature.SET_POSITION
    return features


def _normalize(value: str | None) -> str:
    return str(value or "").strip().lower()
