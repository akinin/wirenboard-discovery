# Wiren Board Discovery Roadmap

## Near term

- Polish `cover` for gates, blinds, and roller shutters:
  - explicit payload mapping for open, close, stop, and position commands;
  - better state mapping for open, closed, opening, closing, stopped, and blocked;
  - better obstruction handling.
- Finish `climate`:
  - thermostat mode;
  - air conditioner mode;
  - mapping numeric WB modes to HA HVAC modes;
  - fan speed mapping;
  - target/current temperature validation.
- Improve sensor classification:
  - device class by units, WB type, name, and enum metadata;
  - water/gas/energy counters;
  - safer `total_increasing` detection.
- Improve icon handling:
  - icon per group;
  - icon per individual control;
  - automatic icon templates by device class and name.

## User interface

- Better group editor:
  - list groups with type and entity count;
  - edit group composition in one place;
  - remove a single control from a group;
  - warn when a control is already used by another group;
  - duplicate a group as a starting point.
- Better discovery filters:
  - custom hidden device list;
  - include/exclude patterns;
  - only new controls;
  - only writable controls;
  - only unselected controls.
- Better composite device creation:
  - wizard presets for gate, cover, thermostat, AC, meter, and sensor cluster;
  - automatic role suggestions.

## Diagnostics

- Persist last successful connection time.
- Persist last background MQTT message.
- Show new, removed, and changed controls.
- Show parsing errors with topic examples.
- Add a repair issue when connection fails repeatedly.

## Reliability

- Add config entry migrations between versions.
- Add unit tests:
  - MQTT topic parser;
  - units to HA `device_class`;
  - groups and exposed controls;
  - cover role mapping;
  - climate role mapping;
  - export/import.
- Add CI:
  - Python syntax;
  - JSON validation;
  - unit tests;
  - optional Home Assistant custom integration checks.

## Distribution

- Prepare HACS support:
  - `hacs.json`;
  - release tags;
  - changelog;
  - installation docs.
- Add release workflow:
  - bump `manifest.json`;
  - create tag;
  - publish GitLab release.

## Done

- MQTT discovery from Wiren Board `/devices/#`.
- Config flow setup.
- Options flow for controls, groups, diagnostics, and connection settings.
- Groups across multiple WB devices.
- Composite `cover` and initial `climate` support.
- Expose selected composite controls as standalone entities for automations.
- Russian and English translations.
- Export/import configuration.
