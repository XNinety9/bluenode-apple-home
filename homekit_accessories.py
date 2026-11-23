"""HomeKit accessories: each node is one accessory of the HomeKit bridge it is wired to."""

from __future__ import annotations

from typing import Any

from pyhap.const import (
    CATEGORY_DOOR_LOCK,
    CATEGORY_FAN,
    CATEGORY_GARAGE_DOOR_OPENER,
    CATEGORY_LIGHTBULB,
    CATEGORY_OTHER,
    CATEGORY_OUTLET,
    CATEGORY_PROGRAMMABLE_SWITCH,
    CATEGORY_SENSOR,
    CATEGORY_SWITCH,
    CATEGORY_THERMOSTAT,
    CATEGORY_WINDOW_COVERING,
)
from pyhap.loader import get_loader
from bluenode.node import Field

from bluenode_apple_home.accessory import AccessoryNode, as_bool, as_choice, as_number, friendly

COMMON = """
### Configuration
- **Name** — the accessory's name in the Home app (default: the node's label).
- **Manufacturer**, **Model** — shown in the accessory's details in the Home app.
- **Battery** — adds a battery: send `{"BatteryLevel": 80, "StatusLowBattery": 0}`.

Wire the **bridge** port to a HomeKit bridge node. Any message whose payload is a dict of HomeKit
characteristic names of the accessory (e.g. `{"On": true}` on a switch) sets them as they are. A payload of the wrong shape is
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



# ---------------------------------------------------------------- with a state


class Light(AccessoryNode):
    type = "homekit-light"
    label = "HomeKit light"
    icon = "lightbulb"
    service = "Lightbulb"
    hap_category = CATEGORY_LIGHTBULB
    KEYS = {"on": "On", "brightness": "Brightness", "color_temperature": "ColorTemperature", "hue": "Hue", "saturation": "Saturation"}  # noqa: RUF012
    __doc__ = f"""A light in the Home app, with brightness and colour as options.

### Input
- `msg.payload` — `true` / `false`, or a dict of what changes:
  `{{"on": true, "brightness": 40, "color_temperature": 300, "hue": 120, "saturation": 50}}`
  (brightness 0–100 %, colour temperature 140–500 mired, hue 0–360°, saturation 0–100 %).

### Output
A change made in the Home app: `msg.payload` is a dict with the one setting that changed
(`{{"brightness": 75}}`, `{{"on": true}}`…), `msg.characteristic` its HomeKit name.

### Options
- **Brightness**, **Colour temperature**, **Colour** (hue and saturation) — what the Home app offers.
{COMMON}"""

    class Config(AccessoryNode.Config):
        brightness: bool = Field(default=True, title="Brightness")
        color_temperature: bool = Field(default=False, title="Colour temperature")
        color: bool = Field(default=False, title="Colour")

    def _keys(self) -> dict[str, str]:
        c = self.config
        on = {"on": "On"} | ({"brightness": "Brightness"} if c.brightness else {})
        on |= {"color_temperature": "ColorTemperature"} if c.color_temperature else {}
        return on | ({"hue": "Hue", "saturation": "Saturation"} if c.color else {})

    def optional_chars(self) -> list[str]:
        return [name for key, name in self._keys().items() if key != "on"]

    def to_chars(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return friendly(payload, self._keys(), "true / false or a dict")
        return {"On": as_bool(payload)}

    def to_payload(self, char: str, value: Any) -> Any:
        key = next(k for k, v in self.KEYS.items() if v == char)
        return {key: bool(value) if char == "On" else value}


class WindowCovering(AccessoryNode):
    type = "homekit-window-covering"
    label = "HomeKit window covering"
    icon = "blinds"
    service = "WindowCovering"
    hap_category = CATEGORY_WINDOW_COVERING
    __doc__ = f"""A blind, shutter or curtain in the Home app.

### Input
- `msg.payload` — the position, 0 (closed) to 100 (open): where the covering is now.

### Output
The position asked in the Home app, 0–100. Move the covering, then send its new position back in.
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        position = as_number(payload)
        return {"CurrentPosition": position, "TargetPosition": position, "PositionState": 2}


class Thermostat(AccessoryNode):
    type = "homekit-thermostat"
    label = "HomeKit thermostat"
    icon = "heater"
    service = "Thermostat"
    hap_category = CATEGORY_THERMOSTAT
    MODES = {"off": 0, "heat": 1, "cool": 2, "auto": 3}  # noqa: RUF012
    __doc__ = f"""A thermostat in the Home app.

### Input
- `msg.payload` — the current temperature (°C), or a dict of what changes:
  `{{"current": 19.5, "target": 21, "mode": "heat"}}` (`mode`: `off`, `heat`, `cool` or `auto`).

### Output
A change made in the Home app: `{{"target": 22.5}}` or `{{"mode": "auto"}}`.
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"CurrentTemperature": as_number(payload)}
        out = friendly(payload, {"current": "CurrentTemperature", "target": "TargetTemperature", "mode": "mode"}, "a dict")
        if "mode" in out:
            mode = as_choice(out.pop("mode"), self.MODES, "off, heat, cool or auto")
            out["TargetHeatingCoolingState"] = mode
            if mode != 3:  # the current state is off, heating or cooling: auto is only a target
                out["CurrentHeatingCoolingState"] = mode
        return out

    def to_payload(self, char: str, value: Any) -> Any:
        if char == "TargetHeatingCoolingState":
            return {"mode": next(k for k, v in self.MODES.items() if v == value)}
        if char == "TargetTemperature":
            return {"target": value}
        return {char: value}


class Lock(AccessoryNode):
    type = "homekit-lock"
    label = "HomeKit lock"
    icon = "lock"
    service = "LockMechanism"
    hap_category = CATEGORY_DOOR_LOCK
    __doc__ = f"""A door lock in the Home app.

### Input
- `msg.payload` — `true` when locked, `false` when unlocked.

### Output
What the Home app asks: `true` lock, `false` unlock. Send the new state back in once done.
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        locked = int(as_bool(payload))
        return {"LockCurrentState": locked, "LockTargetState": locked}

    def to_payload(self, char: str, value: Any) -> Any:
        return bool(value)


class GarageDoor(AccessoryNode):
    type = "homekit-garage-door"
    label = "HomeKit garage door"
    icon = "warehouse"
    service = "GarageDoorOpener"
    hap_category = CATEGORY_GARAGE_DOOR_OPENER
    STATES = {"open": 0, "closed": 1, "opening": 2, "closing": 3, "stopped": 4}  # noqa: RUF012
    TARGETS = {"open": 0, "opening": 0, "closed": 1, "closing": 1}  # noqa: RUF012
    __doc__ = f"""A garage door in the Home app.

### Input
- `msg.payload` — the door's state: `open`, `closed`, `opening`, `closing` or `stopped`.

### Output
What the Home app asks: `"open"` or `"closed"`.
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        state = as_choice(payload, self.STATES, "open, closed, opening, closing or stopped")
        out: dict[str, Any] = {"CurrentDoorState": state, "ObstructionDetected": False}
        target = self.TARGETS.get(str(payload).strip().lower())
        if target is not None:
            out["TargetDoorState"] = target
        return out

    def to_payload(self, char: str, value: Any) -> Any:
        return "open" if value == 0 else "closed"


class Fan(AccessoryNode):
    type = "homekit-fan"
    label = "HomeKit fan"
    icon = "fan"
    service = "Fanv2"
    characteristics = ["RotationSpeed"]  # noqa: RUF012
    hap_category = CATEGORY_FAN
    __doc__ = f"""A fan in the Home app.

### Input
- `msg.payload` — `true` / `false`, or `{{"on": true, "speed": 60}}` (speed 0–100 %).

### Output
A change made in the Home app: `{{"on": true}}` or `{{"speed": 30}}`.
{COMMON}"""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            out = friendly(payload, {"on": "Active", "speed": "RotationSpeed"}, "a dict")
            if "Active" in out:
                out["Active"] = int(as_bool(out["Active"]))
            return out
        return {"Active": int(as_bool(payload))}

    def to_payload(self, char: str, value: Any) -> Any:
        return {"on": bool(value)} if char == "Active" else {"speed": value}


class AnyAccessory(AccessoryNode):
    type = "homekit-accessory"
    label = "HomeKit accessory"
    icon = "house-plug"
    hap_category = CATEGORY_OTHER
    __doc__ = f"""Any HomeKit service, for what the other nodes do not cover (air purifier, valve, security system…).

### Input
- `msg.payload` — a dict of HomeKit characteristic names and values, e.g. `{{"Active": 1, "RotationSpeed": 20}}`.

### Output
A change made in the Home app: `{{"<Characteristic>": value}}`.

### Options
- **Service** — the HomeKit service name, e.g. `AirPurifier`, `Valve`, `SecuritySystem`, `Doorbell`.
- **Characteristics** — optional characteristics to add, separated by commas.
{COMMON}"""

    class Config(AccessoryNode.Config):
        service: str = Field(default="Switch", title="Service", check="required", max_length=64)
        characteristics: str = Field(default="", title="Characteristics", max_length=500, hint="comma-separated, e.g. RotationSpeed, Name")

    def service_name(self) -> str:
        return self.config.service.strip()

    def optional_chars(self) -> list[str]:
        return [c.strip() for c in self.config.characteristics.split(",") if c.strip()]

    def check(self) -> str | None:
        loader = get_loader()
        try:
            loader.get_service(self.service_name())
        except KeyError:
            return f"unknown HomeKit service {self.service_name()!r}"
        for name in self.optional_chars():
            try:
                loader.get_char(name)
            except KeyError:
                return f"unknown HomeKit characteristic {name!r}"
        return None

    def to_payload(self, char: str, value: Any) -> Any:
        return {char: value}


__all__ = [
    "AnyAccessory", "Button", "Contact", "Fan", "GarageDoor", "Humidity", "Leak", "Light", "LightLevel", "Lock",
    "Motion", "Occupancy", "Outlet", "Smoke", "Switch", "Temperature", "Thermostat", "WindowCovering",
]
