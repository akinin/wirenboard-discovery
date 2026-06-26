from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass
class WBControl:
    device_id: str
    control_id: str
    device_name: str | None = None
    control_name: str | None = None
    control_type: str | None = None
    readonly: bool | None = None
    units: str | None = None
    value: str | None = None
    ha_device_id: str | None = None
    ha_device_name: str | None = None
    ha_entity_name: str | None = None
    ha_platform: str | None = None
    ha_device_class: str | None = None
    ha_icon: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.device_id}/{self.control_id}"

    @property
    def title(self) -> str:
        device = self.device_name or self.device_id
        control = self.control_name or self.control_id
        return f"{device}: {control}"

    @property
    def unique_id(self) -> str:
        value = f"wb_{self.device_id}_{self.control_id}".lower()
        return re.sub(r"[^a-z0-9_]+", "_", value).strip("_")

    @property
    def is_readonly(self) -> bool:
        return self.readonly is not False


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def normalize_topic_prefix(prefix: str | None) -> str:
    if not prefix or prefix == "/":
        return "/"
    return "/" + prefix.strip("/")


def localized_title(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("ru") or value.get("en") or next(iter(value.values()), None)
    if value is None:
        return None
    return str(value)
