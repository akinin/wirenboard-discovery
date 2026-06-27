# Changelog

## 0.9.10

- Added real Home Assistant platforms for switch-like group object types: light, fan, lock, siren, and valve.
- Cleaned stale entity registry entries when controls are removed or move to another Home Assistant platform.

## 0.9.9

- Removed controls from Home Assistant when they are removed from a group and are not used by another group.
- Clearing a group object setting also removes that control from separately exposed composite entities.

## 0.9.8

- Removed the group object entity platform field from the UI.
- Group object type now only controls Home Assistant device class.

## 0.9.7

- Changed group object "type" to Home Assistant device class, with a separate entity platform selector.

## 0.9.6

- Added per-object settings inside device groups: entity name, entity type, device class, and icon.
- Allowed object type overrides to move grouped controls between sensor, binary sensor, switch, button, number, and text platforms.

## 0.9.5

- Returned configuration export/import to inline JSON text in the Home Assistant UI.
- Removed the browser download endpoint.

## 0.9.4

- Added an authenticated browser download link for configuration export.

## 0.9.3

- Moved connection settings below diagnostics in the options menu.
- Changed configuration export/import to use JSON files in `/config`.

## 0.9.0

- Added configuration export and import.
- Added editable MQTT connection settings.
- Added better sensor device classes based on units.
- Added composite device groups for covers and climate devices.
- Added Russian and English translations.
