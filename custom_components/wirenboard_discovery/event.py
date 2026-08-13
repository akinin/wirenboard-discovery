from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.components.persistent_notification import async_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .sms import SMS_FIELDS, SmsAttemptTracker
from .sms_entity import WBSmsEntity
from .wb_mqtt import WBRuntimeClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([WBSmsDeliveryEvent(entry, client)])


class WBSmsDeliveryEvent(WBSmsEntity, EventEntity):
    _attr_translation_key = "sms_delivery"
    _attr_event_types = ["sent", "failed"]

    def __init__(self, entry: ConfigEntry, client: WBRuntimeClient) -> None:
        super().__init__(entry, client, "delivery")
        self._entry_id = entry.entry_id
        self._tracker = SmsAttemptTracker()
        self._cancel_pending: Any = None

    async def async_added_to_hass(self) -> None:
        for field in SMS_FIELDS:
            self._client.subscribe_value(
                f"sms_sender/{field}",
                lambda value, current_field=field: self._handle_value(
                    current_field, value
                ),
            )
        baseline = self._tracker.pending_attempt()
        if baseline is not None:
            self._tracker.mark_emitted(baseline)
            if self._cancel_pending is not None:
                self._cancel_pending()
                self._cancel_pending = None

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel_pending is not None:
            self._cancel_pending()
            self._cancel_pending = None

    def _handle_value(self, field: str, value: str | None) -> None:
        if not self._tracker.update(field, value):
            return
        if self._cancel_pending is not None:
            self._cancel_pending()
        self._cancel_pending = async_call_later(
            self.hass,
            0.35,
            self._async_emit_pending,
        )

    async def _async_emit_pending(self, _now) -> None:
        self._cancel_pending = None
        attempt = self._tracker.pending_attempt()
        if attempt is None:
            return
        self._tracker.mark_emitted(attempt)

        event_type = "failed" if attempt.failed else "sent"
        self._trigger_event(
            event_type,
            {
                "recipient": attempt.recipient,
                "message": attempt.message,
                "result": attempt.result,
                "sent_time": attempt.sent_time,
            },
        )
        self.async_write_ha_state()

        if attempt.failed:
            async_create(
                self.hass,
                (
                    f"Не удалось отправить SMS на {attempt.recipient or 'неизвестный номер'}."
                    f"\n\n{attempt.result or 'Wiren Board не сообщил причину.'}"
                ),
                title="Ошибка отправки SMS через Wiren Board",
                notification_id=f"wirenboard_sms_error_{self._entry_id}",
            )
