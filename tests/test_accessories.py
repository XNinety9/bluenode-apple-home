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
