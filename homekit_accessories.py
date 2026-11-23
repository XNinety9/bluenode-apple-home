"""HomeKit accessories: each node is one accessory of the HomeKit bridge it is wired to."""

from __future__ import annotations

from typing import Any

from pyhap.const import (
    CATEGORY_OUTLET,
    CATEGORY_PROGRAMMABLE_SWITCH,
    CATEGORY_SENSOR,
    CATEGORY_SWITCH,
)

from bluenode_apple_home.accessory import AccessoryNode, as_bool, as_choice, as_number

COMMON = """
### Configuration
- **Name** — the accessory's name in the Home app (default: the node's label).
- **Manufacturer**, **Model** — shown in the accessory's details in the Home app.
- **Battery** — adds a battery: send `{"BatteryLevel": 80, "StatusLowBattery": 0}`.

Wire the **bridge** port to a HomeKit bridge node. Any message whose payload is a dict of HomeKit
characteristic names (e.g. `{"StatusActive": false}`) sets them as they are. A payload of the wrong shape is
an error (catch it with a Catch node); nothing is sent to the Home app then.
"""


def _sensor_help(what: str, payload: str) -> str:
    return f"""{what}

### Input
- `msg.payload` — {payload}

The Home app only reads it: the node has no output.
{COMMON}"""


# ---------------------------------------------------------------- switches


class Switch(AccessoryNode):
    type = "homekit-switch"
    label = "HomeKit switch"
    icon = "toggle-right"
    service = "Switch"
    hap_category = CATEGORY_SWITCH
    __doc__ = f"""A switch in the Home app.

### Input
- `msg.payload` — `true` / `false` (also `on` / `off`, `1` / `0`): shows the switch on or off.

### Output
When it is switched in the Home app (or by Siri, an automation): `msg.payload` `true` / `false`,
`msg.characteristic` `"On"`, `msg.source` `"homekit"`. A value sent by the flow does not come back out.
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        return {"On": as_bool(payload)}

    def to_payload(self, char: str, value: Any) -> Any:
        return bool(value)


class Outlet(Switch):
    type = "homekit-outlet"
    label = "HomeKit outlet"
    icon = "plug"
    service = "Outlet"
    hap_category = CATEGORY_OUTLET
    __doc__ = Switch.__doc__.replace("A switch in the Home app.", "A power outlet in the Home app.").replace(
        "shows the switch", "shows the outlet"
    )

    def to_chars(self, payload: Any) -> dict[str, Any]:
        on = as_bool(payload)
        return {"On": on, "OutletInUse": on}


class Button(AccessoryNode):
    type = "homekit-button"
    label = "HomeKit button"
    icon = "circle-dot"
    service = "StatelessProgrammableSwitch"
    hap_category = CATEGORY_PROGRAMMABLE_SWITCH
    PRESSES = {"single": 0, "double": 1, "long": 2}  # noqa: RUF012
    __doc__ = f"""A button in the Home app: each press runs the Home automations set for it.

### Input
- `msg.payload` — `"single"`, `"double"` or `"long"`: the press. In the Home app, set what each press does
  (accessory › Button settings).
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        return {"ProgrammableSwitchEvent": as_choice(payload, self.PRESSES, "single, double or long")}


# ---------------------------------------------------------------- sensors


class Temperature(AccessoryNode):
    type = "homekit-temperature"
    label = "HomeKit temperature"
    icon = "thermometer"
    service = "TemperatureSensor"
    hap_category = CATEGORY_SENSOR
    __doc__ = _sensor_help("A temperature sensor in the Home app.", "the temperature in °C (−50 to 100).")

    def setup(self, service) -> None:  # noqa: ANN001
        service.get_characteristic("CurrentTemperature").override_properties({"minValue": -50, "maxValue": 100, "minStep": 0.1})

    def to_chars(self, payload: Any) -> dict[str, Any]:
        return {"CurrentTemperature": as_number(payload)}


class Humidity(AccessoryNode):
    type = "homekit-humidity"
    label = "HomeKit humidity"
    icon = "droplets"
    service = "HumiditySensor"
    hap_category = CATEGORY_SENSOR
    __doc__ = _sensor_help("A humidity sensor in the Home app.", "the relative humidity in % (0 to 100).")

    def to_chars(self, payload: Any) -> dict[str, Any]:
        return {"CurrentRelativeHumidity": as_number(payload)}


class LightLevel(AccessoryNode):
    type = "homekit-light-level"
    label = "HomeKit light level"
    icon = "sun"
    service = "LightSensor"
    hap_category = CATEGORY_SENSOR
    __doc__ = _sensor_help("A light sensor in the Home app.", "the illuminance in lux (0 is shown as 0.0001, HomeKit's minimum).")

    def to_chars(self, payload: Any) -> dict[str, Any]:
        return {"CurrentAmbientLightLevel": max(as_number(payload), 0.0001)}


class _Detector(AccessoryNode):
    """A sensor whose state is detected / not detected."""

    char = ""
    as_int = True

    def to_chars(self, payload: Any) -> dict[str, Any]:
        detected = as_bool(payload)
        return {self.char: int(detected) if self.as_int else detected}


class Motion(_Detector):
    type = "homekit-motion"
    label = "HomeKit motion"
    icon = "footprints"
    service = "MotionSensor"
    hap_category = CATEGORY_SENSOR
    char = "MotionDetected"
    as_int = False
    __doc__ = _sensor_help("A motion sensor in the Home app.", "`true` when motion is detected, `false` otherwise.")


class Occupancy(_Detector):
    type = "homekit-occupancy"
    label = "HomeKit occupancy"
    icon = "user-check"
    service = "OccupancySensor"
    hap_category = CATEGORY_SENSOR
    char = "OccupancyDetected"
    __doc__ = _sensor_help("An occupancy sensor in the Home app.", "`true` when someone is there, `false` otherwise.")


class Contact(AccessoryNode):
    type = "homekit-contact"
    label = "HomeKit contact"
    icon = "door-closed"
    service = "ContactSensor"
    hap_category = CATEGORY_SENSOR
    __doc__ = _sensor_help("A door or window contact in the Home app.", "`true` when closed, `false` when open.")

    def to_chars(self, payload: Any) -> dict[str, Any]:
        return {"ContactSensorState": 0 if as_bool(payload) else 1}


class Leak(_Detector):
    type = "homekit-leak"
    label = "HomeKit leak"
    icon = "waves"
    service = "LeakSensor"
    hap_category = CATEGORY_SENSOR
    char = "LeakDetected"
    __doc__ = _sensor_help("A water leak sensor in the Home app.", "`true` when a leak is detected, `false` otherwise.")


class Smoke(_Detector):
    type = "homekit-smoke"
    label = "HomeKit smoke"
    icon = "flame"
    service = "SmokeSensor"
    hap_category = CATEGORY_SENSOR
    char = "SmokeDetected"
    __doc__ = _sensor_help("A smoke detector in the Home app.", "`true` when smoke is detected, `false` otherwise.")


__all__ = ["Button", "Contact", "Humidity", "Leak", "LightLevel", "Motion", "Occupancy", "Outlet", "Smoke", "Switch", "Temperature"]
