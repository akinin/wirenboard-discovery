# Changelog

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
