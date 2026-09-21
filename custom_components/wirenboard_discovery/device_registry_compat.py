"""Device registry access compatible with HA 2026.6 and newer releases."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


def get_device_by_identifier(
    registry: dr.DeviceRegistry, identifier: str, entry_id: str
) -> dr.DeviceEntry | None:
    """Resolve an identifier within its owning config entry when supported."""
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(
            (DOMAIN, identifier), entry_id
        )
    # HA 2026.6/2026.7 predate config-entry-scoped device lookups.
    return registry.async_get_device(identifiers={(DOMAIN, identifier)})


def device_belongs_to_entry(device: dr.DeviceEntry, entry_id: str) -> bool:
    """Check ownership without accessing deprecated config_entries on new HA."""
    if getattr(device, "is_composite_device", False):
        # Restored composite IDs represent multiple split devices. Their
        # config_entry_id names only the primary split, not every owner.
        return entry_id in device.config_entries
    if hasattr(device, "config_entry_id"):
        return device.config_entry_id == entry_id
    return entry_id in device.config_entries
