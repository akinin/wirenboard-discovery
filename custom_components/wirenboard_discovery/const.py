from __future__ import annotations

DOMAIN = "wirenboard_discovery"
SERVICE_SEND_SMS = "send_sms"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PHONE = "phone"
ATTR_MESSAGE = "message"

CONF_PREFIX = "prefix"
CONF_SELECTED_CONTROLS = "selected_controls"
CONF_INVERTED_BINARY_SENSORS = "inverted_binary_sensors"
CONF_REMOVED_CONTROLS = "removed_controls"
CONF_DEVICE_GROUPS = "device_groups"
CONF_SHOW_SYSTEM_DEVICES = "show_system_devices"

DEFAULT_HOST = ""
DEFAULT_PORT = 1883
DEFAULT_PREFIX = "/"
DEFAULT_SHOW_SYSTEM_DEVICES = False

PLATFORMS = ["binary_sensor", "button", "climate", "cover", "number", "select", "sensor", "switch", "text"]

DISCOVERY_SECONDS = 4
