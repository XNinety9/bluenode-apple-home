"""Accessory nodes: values from flows to Home, writes from Home to flows."""

from __future__ import annotations

import asyncio

import pytest

import homekit_accessories as hk
from bluenode.testing import NodeHarness

from conftest import char

# (class, simple input, characteristic, value in HAP)
SIMPLE = [
    (hk.Switch, True, "On", True),
    (hk.Switch, "off", "On", False),
    (hk.Outlet, 1, "On", True),
    (hk.Temperature, 21.5, "CurrentTemperature", 21.5),
    (hk.Temperature, -12, "CurrentTemperature", -12),
    (hk.Humidity, 55, "CurrentRelativeHumidity", 55),
    (hk.LightLevel, 0, "CurrentAmbientLightLevel", 0.0001),
    (hk.LightLevel, 320, "CurrentAmbientLightLevel", 320),
    (hk.Motion, True, "MotionDetected", True),
    (hk.Occupancy, True, "OccupancyDetected", 1),
    (hk.Contact, True, "ContactSensorState", 0),
    (hk.Contact, False, "ContactSensorState", 1),
    (hk.Leak, "on", "LeakDetected", 1),
    (hk.Smoke, False, "SmokeDetected", 0),
]


@pytest.mark.parametrize("cls, payload, name, value", SIMPLE)
async def test_simple_input_sets_home(wire, cls, payload, name, value) -> None:
    h = await wire(cls)
    await h.input({"payload": payload})
    assert char(h, name).value == pytest.approx(value) if isinstance(value, float) else char(h, name).value == value
    assert h.sent == []  # values from the flow are not sent back (no echo)


@pytest.mark.parametrize("press, event", [("single", 0), ("double", 1), ("long", 2)])
async def test_button_sends_a_press_event(wire, monkeypatch, press, event) -> None:
    h = await wire(hk.Button)
    c = char(h, "ProgrammableSwitchEvent")
    seen = []
    monkeypatch.setattr(h.node.acc, "publish", lambda value, char, *_a, **_k: seen.append(value))
    await h.input({"payload": press})
    await h.input({"payload": press})  # the same press twice: two events
    assert seen == [event, event]


def test_every_node_is_a_home_accessory() -> None:
    for cls in (hk.Switch, hk.Outlet, hk.Temperature, hk.Humidity, hk.LightLevel, hk.Motion, hk.Occupancy, hk.Contact, hk.Leak, hk.Smoke, hk.Button):
        d = cls.describe()
        assert d["type"].startswith("homekit-") and d["category"] == "home"
        assert cls.uses == {"bridge": "homekit"}
        assert cls.help_text()


@pytest.mark.parametrize("cls, write, payload", [(hk.Switch, True, True), (hk.Outlet, False, False)])
async def test_home_write_comes_out(wire, cls, write, payload) -> None:
    h = await wire(cls, {"name": "Lamp"})
    char(h, "On").client_update_value(write)
    await asyncio.sleep(0.05)
    assert len(h.sent) == 1
    out, msg = h.sent[0]
    assert out == 0
    assert {k: msg[k] for k in ("payload", "characteristic", "value", "source", "topic")} == {
        "payload": payload,
        "characteristic": "On",
        "value": write,
        "source": "homekit",
        "topic": "Lamp",
    }


async def test_dict_sets_characteristics_by_name(wire) -> None:
    h = await wire(hk.Temperature, {"battery": True})
    await h.input({"payload": {"CurrentTemperature": 19, "BatteryLevel": 40, "StatusLowBattery": 1}})
    assert char(h, "CurrentTemperature").value == 19
    assert char(h, "BatteryLevel", "BatteryService").value == 40


@pytest.mark.parametrize(
    "cls, payload, match",
    [
        (hk.Temperature, "warm", "number"),
        (hk.Switch, "maybe", "true or false"),
        (hk.Button, "triple", "single, double or long"),
        (hk.Switch, {"Nope": 1}, "Nope"),
        (hk.Temperature, {"BatteryLevel": 3}, "BatteryLevel"),  # no battery option
    ],
)
async def test_bad_input_is_an_error_and_changes_nothing(wire, cls, payload, match) -> None:
    h = await wire(cls)
    with pytest.raises(ValueError, match=match):
        await h.node.on_message({"payload": payload}, h.node.send)


async def test_dict_is_all_or_nothing(wire) -> None:
    h = await wire(hk.Outlet)
    with pytest.raises(ValueError):
        await h.node.on_message({"payload": {"On": True, "Nope": 1}}, h.node.send)
    assert char(h, "On").value is False


async def test_no_bridge() -> None:
    h = NodeHarness(hk.Switch, {})
    await h.node.on_start()
    assert h.status == {"color": "red", "text": "connect a HomeKit bridge"}
    with pytest.raises(RuntimeError, match="connect a HomeKit bridge"):
        await h.node.on_message({"payload": True}, h.node.send)


async def test_accessory_is_on_the_bridge_with_its_name(wire, bridge) -> None:
    h = await wire(hk.Switch, {"name": "Desk lamp", "manufacturer": "Acme", "model": "X1"})
    assert bridge.host.bridge.accessories[h.node.acc.aid] is h.node.acc
    info = h.node.acc.get_service("AccessoryInformation")
    assert info.get_characteristic("Name").value == "Desk lamp"
    assert info.get_characteristic("Manufacturer").value == "Acme"
    await h.node.on_stop()
    assert h.node.acc.aid in bridge.host.bridge.accessories  # leaves only after the linger delay


# ---- stateful accessories


async def home_writes(h, name, value, service=None):
    h.sent.clear()
    char(h, name, service).client_update_value(value)
    await asyncio.sleep(0.05)
    assert len(h.sent) == 1, h.sent
    return h.sent[0][1]


async def test_light_simple_and_dict(wire) -> None:
    h = await wire(hk.Light, {"brightness": True, "color_temperature": True, "color": True})
    await h.input({"payload": True})
    assert char(h, "On").value is True
    await h.input({"payload": {"on": False, "brightness": 40, "color_temperature": 300, "hue": 120, "saturation": 50}})
    assert (char(h, "On").value, char(h, "Brightness").value, char(h, "ColorTemperature").value) == (False, 40, 300)
    assert (char(h, "Hue").value, char(h, "Saturation").value) == (120, 50)
    msg = await home_writes(h, "Brightness", 75)
    assert msg["payload"] == {"brightness": 75} and msg["characteristic"] == "Brightness"
    msg = await home_writes(h, "On", True)
    assert msg["payload"] == {"on": True}


async def test_light_without_colour_refuses_hue(wire) -> None:
    h = await wire(hk.Light, {"brightness": True})
    assert char(h, "Brightness") is not None
    with pytest.raises(ValueError, match="hue"):
        await h.node.on_message({"payload": {"hue": 10}}, h.node.send)


async def test_window_covering(wire) -> None:
    h = await wire(hk.WindowCovering)
    await h.input({"payload": 30})
    assert (char(h, "CurrentPosition").value, char(h, "TargetPosition").value, char(h, "PositionState").value) == (30, 30, 2)
    assert (await home_writes(h, "TargetPosition", 80))["payload"] == 80


async def test_thermostat(wire) -> None:
    h = await wire(hk.Thermostat)
    await h.input({"payload": {"current": 19.5, "target": 21, "mode": "heat"}})
    assert char(h, "CurrentTemperature").value == 19.5
    assert char(h, "TargetTemperature").value == 21
    assert char(h, "TargetHeatingCoolingState").value == 1
    assert char(h, "CurrentHeatingCoolingState").value == 1
    assert (await home_writes(h, "TargetTemperature", 22.5))["payload"] == {"target": 22.5}
    assert (await home_writes(h, "TargetHeatingCoolingState", 3))["payload"] == {"mode": "auto"}
    with pytest.raises(ValueError, match="off, heat, cool or auto"):
        await h.node.on_message({"payload": {"mode": "warm"}}, h.node.send)


async def test_lock(wire) -> None:
    h = await wire(hk.Lock)
    await h.input({"payload": True})
    assert (char(h, "LockCurrentState").value, char(h, "LockTargetState").value) == (1, 1)
    assert (await home_writes(h, "LockTargetState", 0))["payload"] is False


async def test_garage_door(wire) -> None:
    h = await wire(hk.GarageDoor)
    await h.input({"payload": "open"})
    assert (char(h, "CurrentDoorState").value, char(h, "TargetDoorState").value) == (0, 0)
    await h.input({"payload": "closing"})
    assert (char(h, "CurrentDoorState").value, char(h, "TargetDoorState").value) == (3, 1)
    assert (await home_writes(h, "TargetDoorState", 0))["payload"] == "open"
    with pytest.raises(ValueError, match="open, closed"):
        await h.node.on_message({"payload": "ajar"}, h.node.send)


async def test_fan(wire) -> None:
    h = await wire(hk.Fan)
    await h.input({"payload": {"on": True, "speed": 60}})
    assert (char(h, "Active").value, char(h, "RotationSpeed").value) == (1, 60)
    await h.input({"payload": False})
    assert char(h, "Active").value == 0
    assert (await home_writes(h, "RotationSpeed", 30))["payload"] == {"speed": 30}
    assert (await home_writes(h, "Active", 1))["payload"] == {"on": True}


async def test_generic_accessory(wire) -> None:
    h = await wire(hk.AnyAccessory, {"service": "AirPurifier", "characteristics": "RotationSpeed, LockPhysicalControls"})
    await h.input({"payload": {"Active": 1, "RotationSpeed": 20}})
    assert char(h, "RotationSpeed").value == 20
    msg = await home_writes(h, "Active", 0)
    assert msg["payload"] == {"Active": 0}


async def test_generic_unknown_service(wire) -> None:
    h = await wire(hk.AnyAccessory, {"service": "Teleporter"})
    assert h.status["color"] == "red" and "Teleporter" in h.status["text"]
    with pytest.raises(RuntimeError):
        await h.node.on_message({"payload": {"On": True}}, h.node.send)


async def test_help_example_dict_is_accepted(wire) -> None:
    assert '{"On": true}' in hk.COMMON
    h = await wire(hk.Switch)
    await h.input({"payload": {"On": True}})
    assert char(h, "On").value is True
