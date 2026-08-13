from __future__ import annotations

from dataclasses import dataclass


SMS_DEVICE_ID = "sms_gateway"
SMS_DEVICE_NAME = "SMS Gateway"
SMS_FIELDS = (
    "last_sent_time",
    "last_message_text",
    "last_recipient_number",
    "last_result",
)


@dataclass(frozen=True)
class SmsAttempt:
    sent_time: str
    message: str
    recipient: str
    result: str

    @property
    def failed(self) -> bool:
        return self.result.casefold().startswith(("ошибка", "error"))


class SmsAttemptTracker:
    """Collect the retained last_* controls into one deduplicated attempt."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.seen: set[str] = set()
        self.pending_time: str | None = None
        self.last_emitted_time: str | None = None

    def update(self, field: str, value: str | None) -> bool:
        if field not in SMS_FIELDS:
            return False
        normalized = "" if value is None else str(value).strip()
        self.values[field] = normalized
        self.seen.add(field)
        if field == "last_sent_time" and normalized != self.last_emitted_time:
            self.pending_time = normalized or None
        return self.pending_time is not None

    @property
    def script_controls_available(self) -> bool:
        return all(field in self.seen for field in SMS_FIELDS)

    def pending_attempt(self) -> SmsAttempt | None:
        if not self.pending_time or not self.script_controls_available:
            return None
        if self.values.get("last_sent_time") != self.pending_time:
            return None
        return SmsAttempt(
            sent_time=self.pending_time,
            message=self.values["last_message_text"],
            recipient=self.values["last_recipient_number"],
            result=self.values["last_result"],
        )

    def mark_emitted(self, attempt: SmsAttempt) -> None:
        self.last_emitted_time = attempt.sent_time
        self.pending_time = None
