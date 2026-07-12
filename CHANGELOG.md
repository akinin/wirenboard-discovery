# Changelog

## 0.10.5

- Wait for the Wiren Board MQTT connection to be fully ready during Home Assistant startup, preventing the first SMS action from being lost after a restart.
- Report an unavailable MQTT connection instead of silently publishing while disconnected.

## 0.10.4

- Reset the Wiren Board SMS command to whitespace after it has been accepted, allowing identical consecutive messages to trigger `whenChanged` reliably.
- Keep SMS sends serialized until the command reset is complete.

## 0.10.3

- Serialized SMS action calls per Wiren Board connection.
- Wait briefly after publishing so `send_sms.js` can clear the control before an identical message is sent again.

## 0.10.2

- Removed the pre-send MQTT reset because rapid reset/send updates can be coalesced by Wiren Board and skip `whenChanged`.
- Repeated identical messages remain supported when `send_sms.js` clears `sms_sender/send` after accepting a command.

## 0.10.1

- Reset the SMS command control before publishing so identical consecutive messages trigger `whenChanged` reliably.

## 0.10.0

- Added the `wirenboard_discovery.send_sms` action using the existing Wiren Board MQTT connection.
- Added dynamic recipient validation and Russian phone number normalization.

## 0.9.4

- Added Zeroconf discovery for Wiren Board controllers announced as `wirenboard-*.local`.

## 0.9.3

- Moved connection settings below diagnostics in the options menu.

## 0.9.0

- Added configuration export and import.
- Added editable MQTT connection settings.
- Added better sensor device classes based on units.
- Added composite device groups for covers and climate devices.
- Added Russian and English translations.
