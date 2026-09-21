# Changelog

## 0.17.1

- Treat live control- and device-level `meta/error` updates strictly as
  availability changes, preventing full config-entry reloads and brief outages
  of all Wiren Board entities when a device reports a transient error.

## 0.17.0

- Localize device, entity, and enum titles using the Home Assistant language,
  with backwards-compatible fallbacks for incomplete WB translations.
- Attach published device metadata to Home Assistant devices and promote both
  WB-STD-001 and legacy controller identity controls to serial, software, and
  hardware version fields.
- Preserve the last stored value when a startup metadata refresh has not yet
  received the corresponding retained state.
- Detect metadata changes for selected controls and reload only this config
  entry after a short debounce; newly discovered controls remain opt-in and
  appear in the options flow from the live MQTT inventory. Initial retained
  MQTT messages are explicitly excluded from reload triggers, and the runtime
  inventory gets a stabilization period before change detection is armed.
- Expand diagnostics with WB-STD-001 adoption, hidden controls, device/control
  errors, device metadata coverage, and active MQTT drivers.

## 0.16.1

- Mark entities unavailable on MQTT disconnect and device-level `meta/error`,
  in addition to control-level errors.
- Remove MQTT callbacks when entities unload, preventing duplicate updates
  after integration reloads.
- Respect the standard `hidden` metadata flag.
- Support read-only and writable `unixtime` controls as timestamp sensors and
  datetime entities.
- Support `wo-switch` controls with assumed state and expose canonical
  `cmd_*` write-only controls as buttons.
- Apply MQTT `precision` as the native step for number entities.

## 0.16.0

- Recognize canonical WB-STD-001 sensor and alarm identifiers, including the
  standard MQTT `alarm` control type, while retaining
  unit- and title-based classification for legacy device templates.
- Supply the canonical unit when older WB metadata omits it.
- Mark canonical controller service channels as diagnostic entities.
- Make entities unavailable while Wiren Board reports a non-empty
  `meta/error`, and restore them when the error is cleared.
- Refresh retained control metadata during startup, while keeping stored
  discovery data as an offline fallback.
- Include a backwards-compatible, bilingual R8C-963S template with corrected
  units and the absent floor sensor disabled by default.

## 0.15.2

- Prefer a device's exact `Mode` control over auxiliary mode switches for
  composite climate entities.
- Resolve numeric HVAC states through each control's enum labels, preventing
  R8C thermostat heating mode from appearing as ventilation.
- Avoid publishing HVAC commands to read-only mode controls.

## 0.15.0

- Add a dedicated SMS Gateway device without exposing raw `sms_sender` controls.
- Add diagnostic entities for the required WB script and the last SMS attempt.
- Emit Home Assistant `sent` and `failed` SMS events from confirmed Wiren Board results.
- Create a persistent Home Assistant notification when Wiren Board reports an SMS error.

## 0.14.1

- Create a missing target device when existing entities are moved into a new logical group.
- Preserve entity IDs while regrouping controls that were already registered in Home Assistant.
- Keep read-only enum status sensors non-numeric inside gas and water meter groups.

## 0.14.0

- Normalize common Wiren Board units (`deg C`, `%, RH`, `m^3`) to canonical Home Assistant units.
- Use `dBA` for WB sound level controls that do not publish an explicit unit and recognize battery percentage sensors.
- Display localized labels for read-only enum controls instead of their numeric keys.
- Ignore blank numeric MQTT values instead of raising entity state errors.
- Provide valid localized fan modes for composite climate entities and publish the corresponding enum keys.
- Move existing entities when controls join or leave logical device groups and remove empty former devices.
- Move YAML file reads and MQTT dependency loading out of the Home Assistant event loop.
- Avoid long-term statistics for untyped numeric status and enum controls.

## 0.13.0

- Added Home Assistant `select` entities for writable Wiren Board controls with enum metadata.
- Display localized enum titles and publish the corresponding enum key when an option is selected.

## 0.12.2

- Added "Gas meter" and "Water meter" to the existing device type selector used when creating or editing a group.
- Apply the selected group type to its numeric volume sensor without a separate configuration menu.

## 0.12.1

- Added `gas` and `water` to the existing Wiren Board sensor type mapping and removed the separate meter configuration menu.
- Automatically use `m³` and `total_increasing` for mapped gas and water counters.
- Remove empty integration devices even when their last entity was deleted before the current cleanup run.

## 0.12.0

- Normalize cubic metre units from `m^3` and `m3` to the Home Assistant unit `m³`.
- Added configuration for assigning volume sensors as gas or water meters.
- Show Home Assistant entity names in binary sensor inversion and meter configuration lists.
- Removed controls from the integration when they are removed from a group instead of moving them back to automatically created devices.
- Clean up entity and empty device registry entries for controls removed from groups.
- Added "Remove unwanted entities" for cleaning up standalone entities created by earlier versions.
- Moved binary sensor inversion below group removal in the options menu.

## 0.11.0

- Added per-entity state inversion for read-only binary sensors.
- Removed "Select items" from the options menu to prevent removed entities from leaving orphaned Home Assistant devices.
- Included binary sensor inversion settings in configuration export and import.

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
