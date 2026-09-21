from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import replace
from typing import Optional

from paho.mqtt import client as mqtt

from .const import DISCOVERY_SECONDS
from .models import WBControl, localized_title, normalize_topic_prefix, parse_bool

_LOGGER = logging.getLogger(__name__)

_TRANSIENT_METADATA_KEYS = frozenset({"error"})


ValueCallback = Callable[[Optional[str]], None]
MetaCallback = Callable[[WBControl], None]
DeviceMetaCallback = Callable[[dict[str, object]], None]
ConnectionCallback = Callable[[bool], None]
InventoryCallback = Callable[[], None]
UnsubscribeCallback = Callable[[], None]


class WBDiscoveryError(Exception):
    """Raised when the Wiren Board MQTT broker cannot be reached."""


@dataclass
class WBDiscoverySnapshot:
    controls: dict[str, WBControl]
    device_meta: dict[str, dict[str, object]]
    message_count: int
    last_topic: str | None = None
    last_payload: str | None = None
    parse_errors: int = 0
    elapsed_seconds: float = 0


class WBTopicParser:
    def __init__(self, prefix: str) -> None:
        self.prefix = normalize_topic_prefix(prefix)
        self.devices: dict[str, str] = {}
        self.device_meta: dict[str, dict[str, object]] = {}
        self.controls: dict[str, WBControl] = {}

    def parse_message(self, topic: str, payload: str) -> None:
        normalized = self._strip_prefix(topic)
        if not normalized:
            return

        parts = normalized.split("/")
        if len(parts) >= 4 and parts[0] == "devices" and parts[2] == "controls":
            self._parse_control(parts, payload)
            return

        if len(parts) >= 3 and parts[0] == "devices" and parts[2] == "meta":
            self._parse_device_meta(parts, payload)

    def _strip_prefix(self, topic: str) -> str | None:
        if self.prefix == "/":
            return topic.strip("/")
        prefix = self.prefix.strip("/")
        topic_without_slashes = topic.strip("/")
        if not topic_without_slashes.startswith(prefix + "/"):
            return None
        return topic_without_slashes[len(prefix) + 1 :]

    def _parse_control(self, parts: list[str], payload: str) -> None:
        device_id = parts[1]
        control_id = parts[3]
        key = f"{device_id}/{control_id}"
        control = self.controls.get(key) or WBControl(
            device_id=device_id,
            control_id=control_id,
            device_name=self.devices.get(device_id),
            device_meta=dict(self.device_meta.get(device_id, {})),
        )

        if len(parts) == 4:
            control.value = payload
        elif len(parts) == 5 and parts[4] == "meta":
            self._apply_control_meta(control, _json_or_text(payload))
        elif len(parts) == 6 and parts[4] == "meta":
            self._apply_control_meta(control, {parts[5]: payload})

        self.controls[key] = control
        if len(parts) == 4:
            self._apply_identity_control(control)

    def _apply_identity_control(self, control: WBControl) -> None:
        """Promote published identity controls into HA device metadata."""
        if control.value is None or not str(control.value).strip():
            return
        identity_key = identity_metadata_key(control.control_id)
        if identity_key is None:
            return
        self.device_meta.setdefault(control.device_id, {})[identity_key] = control.value
        self._apply_device_meta(control.device_id)

    def _parse_device_meta(self, parts: list[str], payload: str) -> None:
        device_id = parts[1]
        if len(parts) == 3:
            meta = _json_or_text(payload)
            if isinstance(meta, dict):
                self.device_meta.setdefault(device_id, {}).update(meta)
                name = localized_title(meta.get("title")) or localized_title(meta.get("name"))
                if name:
                    self.devices[device_id] = name
                    self._apply_device_name(device_id, name)
                self._apply_device_meta(device_id)
            return

        if len(parts) == 4:
            key = parts[3]
            self.device_meta.setdefault(device_id, {})[key] = payload
            if key == "name":
                self.devices[device_id] = payload
                self._apply_device_name(device_id, payload)
            self._apply_device_meta(device_id)

    def _apply_control_meta(self, control: WBControl, meta: object) -> None:
        if not isinstance(meta, dict):
            return

        control.meta.update(meta)
        if "type" in meta:
            control.control_type = str(meta["type"])
        if "readonly" in meta:
            control.readonly = parse_bool(str(meta["readonly"]))
        if "title" in meta:
            control.control_name = localized_title(meta["title"])
        elif "name" in meta:
            control.control_name = localized_title(meta["name"])
        if "units" in meta:
            control.units = str(meta["units"])
        elif "unit" in meta:
            control.units = str(meta["unit"])

    def _apply_device_name(self, device_id: str, name: str) -> None:
        for key, control in list(self.controls.items()):
            if control.device_id == device_id:
                self.controls[key] = replace(control, device_name=name)

    def _apply_device_meta(self, device_id: str) -> None:
        meta = dict(self.device_meta.get(device_id, {}))
        for key, control in list(self.controls.items()):
            if control.device_id == device_id:
                self.controls[key] = replace(control, device_meta=meta)


def discover_controls(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    prefix: str,
    timeout: int = DISCOVERY_SECONDS,
) -> dict[str, WBControl]:
    return discover_snapshot(host, port, username, password, prefix, timeout).controls


def discover_snapshot(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    prefix: str,
    timeout: int = DISCOVERY_SECONDS,
) -> WBDiscoverySnapshot:
    parser = WBTopicParser(prefix)
    connected = threading.Event()
    failed: list[str] = []
    stats = {
        "message_count": 0,
        "last_topic": None,
        "last_payload": None,
        "parse_errors": 0,
    }

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if username:
        client.username_pw_set(username, password)

    def on_connect(client, _userdata, _flags, reason_code, _properties) -> None:
        if _reason_code_failed(reason_code):
            failed.append(str(reason_code))
            connected.set()
            return
        topic = f"{normalize_topic_prefix(prefix).rstrip('/')}/devices/#"
        if topic.startswith("//"):
            topic = topic[1:]
        client.subscribe(topic)
        connected.set()

    def on_message(_client, _userdata, message) -> None:
        payload = message.payload.decode("utf-8", errors="replace")
        stats["message_count"] += 1
        stats["last_topic"] = message.topic
        stats["last_payload"] = payload[:300]
        try:
            parser.parse_message(message.topic, payload)
        except Exception:
            stats["parse_errors"] += 1
            _LOGGER.exception("Cannot parse Wiren Board MQTT message from %s", message.topic)

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        started = time.monotonic()
        client.connect(host, port, keepalive=30)
        client.loop_start()
        if not connected.wait(timeout=timeout):
            raise WBDiscoveryError("timeout")
        if failed:
            raise WBDiscoveryError(f"mqtt connection failed: {failed[-1]}")
        time.sleep(timeout)
        return WBDiscoverySnapshot(
            controls=parser.controls,
            device_meta=parser.device_meta,
            message_count=int(stats["message_count"]),
            last_topic=stats["last_topic"],
            last_payload=stats["last_payload"],
            parse_errors=int(stats["parse_errors"]),
            elapsed_seconds=round(time.monotonic() - started, 2),
        )
    except OSError as err:
        raise WBDiscoveryError(str(err)) from err
    finally:
        client.loop_stop()
        client.disconnect()


class WBRuntimeClient:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        prefix: str,
        language: str | None = None,
    ) -> None:
        self._loop = loop
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._prefix = normalize_topic_prefix(prefix)
        self.language = language
        self._parser = WBTopicParser(prefix)
        self._callbacks: dict[str, list[ValueCallback]] = {}
        self._meta_callbacks: dict[str, list[MetaCallback]] = {}
        self._device_meta_callbacks: dict[str, list[DeviceMetaCallback]] = {}
        self._connection_callbacks: list[ConnectionCallback] = []
        self._inventory_callbacks: list[InventoryCallback] = []
        self._connected = threading.Event()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def controls(self) -> dict[str, WBControl]:
        return self._parser.controls

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def async_start(self) -> None:
        await self._loop.run_in_executor(None, self._start)

    async def async_stop(self) -> None:
        await self._loop.run_in_executor(None, self._stop)

    def subscribe_value(
        self, key: str, callback: ValueCallback
    ) -> UnsubscribeCallback:
        self._callbacks.setdefault(key, []).append(callback)
        if key in self._parser.controls:
            callback(self._parser.controls[key].value)
        return lambda: self._remove_callback(self._callbacks, key, callback)

    def subscribe_meta(self, key: str, callback: MetaCallback) -> UnsubscribeCallback:
        self._meta_callbacks.setdefault(key, []).append(callback)
        if key in self._parser.controls:
            callback(self._parser.controls[key])
        return lambda: self._remove_callback(self._meta_callbacks, key, callback)

    def subscribe_device_meta(
        self, device_id: str, callback: DeviceMetaCallback
    ) -> UnsubscribeCallback:
        self._device_meta_callbacks.setdefault(device_id, []).append(callback)
        callback(self._parser.device_meta.get(device_id, {}))
        return lambda: self._remove_callback(
            self._device_meta_callbacks, device_id, callback
        )

    def subscribe_connection(
        self, callback: ConnectionCallback
    ) -> UnsubscribeCallback:
        self._connection_callbacks.append(callback)
        callback(self.connected)

        def unsubscribe() -> None:
            try:
                self._connection_callbacks.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def subscribe_inventory(self, callback: InventoryCallback) -> UnsubscribeCallback:
        self._inventory_callbacks.append(callback)

        def unsubscribe() -> None:
            try:
                self._inventory_callbacks.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def publish_control(self, control: WBControl, value: str) -> None:
        topic = self._topic_for(control, command=True)
        self._client.publish(topic, value)

    def publish_control_by_id(self, device_id: str, control_id: str, value: str) -> None:
        if not self._connected.is_set():
            raise WBDiscoveryError("Wiren Board MQTT connection is not ready")
        topic = f"{self._prefix.rstrip('/')}/devices/{device_id}/controls/{control_id}/on"
        if topic.startswith("//"):
            topic = topic[1:]
        self._client.publish(topic, value)

    def _start(self) -> None:
        self._connected.clear()
        self._client.connect(self._host, self._port, keepalive=30)
        self._client.loop_start()
        if not self._connected.wait(timeout=10):
            self._client.loop_stop()
            self._client.disconnect()
            raise WBDiscoveryError("timeout waiting for Wiren Board MQTT connection")

    def _stop(self) -> None:
        self._connected.clear()
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if _reason_code_failed(reason_code):
            _LOGGER.warning("Wiren Board MQTT connection failed: %s", reason_code)
            return
        self._connected.set()
        _LOGGER.info("Wiren Board MQTT connection is available")
        topic = f"{self._prefix.rstrip('/')}/devices/#"
        if topic.startswith("//"):
            topic = topic[1:]
        client.subscribe(topic)
        self._notify_connection(True)

    def _on_disconnect(
        self, _client, _userdata, _disconnect_flags, _reason_code, _properties
    ) -> None:
        was_connected = self._connected.is_set()
        self._connected.clear()
        if was_connected:
            _LOGGER.warning("Wiren Board MQTT connection was lost")
            self._notify_connection(False)

    def _on_message(self, _client, _userdata, message) -> None:
        payload = message.payload.decode("utf-8", errors="replace")
        control_key = self._control_key_from_topic(message.topic)
        control_device_id = control_key.split("/", 1)[0] if control_key else None
        device_meta_before = (
            _freeze(self._parser.device_meta.get(control_device_id, {}))
            if control_device_id
            else None
        )
        before = self._inventory_signature(message.topic)
        self._parser.parse_message(message.topic, payload)
        after = self._inventory_signature(message.topic)
        key = self._key_from_topic(message.topic)
        if key:
            callbacks = list(self._callbacks.get(key, []))
            for callback in callbacks:
                self._loop.call_soon_threadsafe(callback, payload)

        meta_key = self._control_key_from_topic(message.topic)
        if meta_key and "/meta" in message.topic:
            control = self._parser.controls.get(meta_key)
            if control:
                for callback in list(self._meta_callbacks.get(meta_key, [])):
                    self._loop.call_soon_threadsafe(callback, control)

        device_id = self._device_id_from_meta_topic(message.topic)
        if device_id:
            meta = self._parser.device_meta.get(device_id, {})
            for callback in list(self._device_meta_callbacks.get(device_id, [])):
                self._loop.call_soon_threadsafe(callback, meta)

        if (
            control_device_id
            and device_meta_before
            != _freeze(self._parser.device_meta.get(control_device_id, {}))
        ):
            meta = self._parser.device_meta.get(control_device_id, {})
            for callback in list(
                self._device_meta_callbacks.get(control_device_id, [])
            ):
                self._loop.call_soon_threadsafe(callback, meta)

        # Retained messages build the initial inventory after every MQTT
        # subscription. They are not live metadata changes and must never
        # trigger a config-entry reload loop.
        if before != after and not message.retain:
            for callback in list(self._inventory_callbacks):
                self._loop.call_soon_threadsafe(callback)

    def _inventory_signature(self, topic: str) -> tuple | None:
        control_key = self._control_key_from_topic(topic)
        if control_key:
            control = self._parser.controls.get(control_key)
            if control is None:
                return None
            return control_metadata_signature(control)
        device_id = self._device_id_from_meta_topic(topic)
        if device_id:
            return _metadata_inventory_signature(
                self._parser.device_meta.get(device_id, {})
            )
        return None

    def _key_from_topic(self, topic: str) -> str | None:
        normalized = self._parser._strip_prefix(topic)
        if not normalized:
            return None
        parts = normalized.split("/")
        if len(parts) == 4 and parts[0] == "devices" and parts[2] == "controls":
            return f"{parts[1]}/{parts[3]}"
        return None

    def _control_key_from_topic(self, topic: str) -> str | None:
        normalized = self._parser._strip_prefix(topic)
        if not normalized:
            return None
        parts = normalized.split("/")
        if len(parts) >= 4 and parts[0] == "devices" and parts[2] == "controls":
            return f"{parts[1]}/{parts[3]}"
        return None

    def _device_id_from_meta_topic(self, topic: str) -> str | None:
        normalized = self._parser._strip_prefix(topic)
        if not normalized:
            return None
        parts = normalized.split("/")
        if len(parts) >= 3 and parts[0] == "devices" and parts[2] == "meta":
            return parts[1]
        return None

    def _notify_connection(self, connected: bool) -> None:
        for callback in list(self._connection_callbacks):
            self._loop.call_soon_threadsafe(callback, connected)

    @staticmethod
    def _remove_callback(callbacks: dict, key: str, callback: Callable) -> None:
        registered = callbacks.get(key)
        if not registered:
            return
        try:
            registered.remove(callback)
        except ValueError:
            return
        if not registered:
            callbacks.pop(key, None)

    def _topic_for(self, control: WBControl, command: bool = False) -> str:
        topic = f"{self._prefix.rstrip('/')}/devices/{control.device_id}/controls/{control.control_id}"
        if topic.startswith("//"):
            topic = topic[1:]
        if command:
            return f"{topic}/on"
        return topic


def _reason_code_failed(reason_code) -> bool:
    is_failure = getattr(reason_code, "is_failure", None)
    if is_failure is not None:
        return bool(is_failure)
    try:
        return int(reason_code) != 0
    except (TypeError, ValueError):
        return str(reason_code) not in {"0", "Success"}


def _json_or_text(payload: str) -> object:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload


def identity_metadata_key(control_id: str) -> str | None:
    normalized = " ".join(control_id.strip().lower().replace("_", " ").split())
    return {
        "sn": "serial_number",
        "short sn": "serial_number",
        "serial": "serial_number",
        "serial number": "serial_number",
        "fw": "sw_version",
        "firmware": "sw_version",
        "release name": "sw_version",
        "hw": "hw_version",
        "hw revision": "hw_version",
        "hardware": "hw_version",
        "batch no": "hw_batch",
        "hw batch": "hw_batch",
        "manufacturing date": "manufacturing_date",
    }.get(normalized)


def control_metadata_signature(control: WBControl) -> tuple:
    return (
        control.device_name,
        control.control_name,
        control.control_type,
        control.readonly,
        control.units,
        _metadata_inventory_signature(control.meta),
        _metadata_inventory_signature(control.device_meta),
    )


def _metadata_inventory_signature(metadata: dict[str, object]) -> object:
    """Freeze structural metadata without live availability state."""
    return _freeze(
        {
            key: value
            for key, value in metadata.items()
            if str(key).lower() not in _TRANSIENT_METADATA_KEYS
        }
    )


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value
