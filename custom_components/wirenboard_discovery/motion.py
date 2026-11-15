from __future__ import annotations

from typing import Any

from .const import CONF_MOTION_OFF_DELAY, CONF_MOTION_THRESHOLD
from .models import WBControl

DEFAULT_MOTION_THRESHOLD = 100
DEFAULT_MOTION_OFF_DELAY = 5
MAX_MOTION_LEVEL = 65534  # 0xFFFF is the Modbus error value.
MAX_MOTION_OFF_DELAY = 3600

_WB_MSW_DEVICE_TYPES = {"wb-msw", "wb-msw2", "wb-msw-v3", "wb-msw-v4", "wb-msw-lora-v4"}


def is_wb_msw(device_id: str) -> bool:
    return device_id.lower().partition("_")[0] in _WB_MSW_DEVICE_TYPES


def is_msw_max_motion(control: WBControl) -> bool:
    return (
        is_wb_msw(control.device_id)
        and control.control_id.lower() in {"max motion", "max_motion"}
        and control.control_type == "value"
        and control.is_readonly
        and not control.is_hidden
    )


def motion_unique_id(source_unique_id: str) -> str:
    return f"{source_unique_id}:motion"


def motion_level(value: str | None) -> float | None:
    try:
        level = float(value)
    except (TypeError, ValueError):
        return None
    return level if 0 <= level <= MAX_MOTION_LEVEL else None


def motion_config(settings: Any) -> dict[str, int]:
    """Validate motion options received from a selector or configuration import."""
    if not isinstance(settings, dict):
        raise ValueError("Motion settings must be an object")
    threshold = settings.get(CONF_MOTION_THRESHOLD, DEFAULT_MOTION_THRESHOLD)
    off_delay = settings.get(CONF_MOTION_OFF_DELAY, DEFAULT_MOTION_OFF_DELAY)
    if (
        type(threshold) not in {int, float}
        or not 1 <= threshold <= MAX_MOTION_LEVEL
        or type(off_delay) not in {int, float}
        or not 0 <= off_delay <= MAX_MOTION_OFF_DELAY
        or threshold != int(threshold)
        or off_delay != int(off_delay)
    ):
        raise ValueError("Invalid motion threshold or off delay")
    return {
        CONF_MOTION_THRESHOLD: int(threshold),
        CONF_MOTION_OFF_DELAY: int(off_delay),
    }
