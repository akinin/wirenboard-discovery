from __future__ import annotations

import re


_CANONICAL_ID = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")

DIAGNOSTIC_IDS = {
    "sn",
    "fw",
    "uptime",
    "hw_batch",
    "t_mcu",
    "v_mcu",
    "v_vin",
}


def is_canonical_id(control_id: str) -> bool:
    """Return whether an MQTT control id follows WB-STD-001."""
    return len(control_id) <= 64 and _CANONICAL_ID.fullmatch(control_id) is not None


def canonical_sensor_device_class(control_id: str) -> str | None:
    """Map WB-STD-001 canonical ids to Home Assistant device classes."""
    control_id = control_id.lower()
    exact = {
        "temperature": "temperature",
        "humidity": "humidity",
        "co2": "carbon_dioxide",
        "illuminance": "illuminance",
        "sound_level": "sound_pressure",
        "pressure": "atmospheric_pressure",
        "pm25": "pm25",
        "voc": "volatile_organic_compounds",
        "frequency": "frequency",
        "uptime": "duration",
    }
    if control_id in exact:
        return exact[control_id]

    prefixes = (
        ("setpoint_t_", "temperature"),
        ("humidity_", "humidity"),
        ("illuminance_", "illuminance"),
        ("sound_level_", "sound_pressure"),
        ("pressure_", "pressure"),
        ("t_", "temperature"),
        ("u_", "voltage"),
        ("v_", "voltage"),
        ("i_", "current"),
        ("f_", "frequency"),
        ("p_", "power"),
        ("q_", "reactive_power"),
        ("s_", "apparent_power"),
        ("e_", "energy"),
        ("pf_", "power_factor"),
        ("co2_", "carbon_dioxide"),
        ("pm25_", "pm25"),
        ("voc_", "volatile_organic_compounds"),
    )
    for prefix, device_class in prefixes:
        if control_id.startswith(prefix):
            return device_class
    return None


def canonical_sensor_unit(control_id: str) -> str | None:
    """Return the WB-STD-001 unit when legacy metadata omits it."""
    control_id = control_id.lower()
    exact = {
        "temperature": "deg C",
        "humidity": "%",
        "co2": "ppm",
        "illuminance": "lx",
        "sound_level": "dB",
        "pressure": "mbar",
        "pm25": "ug/m^3",
        "voc": "ppm",
        "frequency": "Hz",
        "uptime": "s",
    }
    if control_id in exact:
        return exact[control_id]

    prefixes = (
        ("setpoint_t_", "deg C"),
        ("setpoint_humidity_", "%"),
        ("t_", "deg C"),
        ("humidity_", "%"),
        ("illuminance_", "lx"),
        ("sound_level_", "dB"),
        ("pressure_", "mbar"),
        ("u_", "V"),
        ("v_", "V"),
        ("i_", "A"),
        ("f_", "Hz"),
        ("p_", "W"),
        ("q_", "var"),
        ("s_", "VA"),
        ("e_", "kWh"),
        ("co2_", "ppm"),
        ("pm25_", "ug/m^3"),
        ("voc_", "ppm"),
    )
    for prefix, unit in prefixes:
        if control_id.startswith(prefix):
            return unit
    return None


def canonical_binary_device_class(control_id: str) -> str | None:
    """Map canonical binary ids without guessing from translated titles."""
    control_id = control_id.lower()
    if control_id in {"alarm_motion", "motion"}:
        return "motion"
    if control_id == "alarm_tamper":
        return "tamper"
    if control_id.startswith("alarm_"):
        return "problem"
    return None


def is_diagnostic_id(control_id: str) -> bool:
    return control_id.lower() in DIAGNOSTIC_IDS
