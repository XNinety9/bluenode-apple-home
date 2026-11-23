"""The HomeKit bridge node (homekit_bridge.py)."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest

import homekit_bridge
from bluenode.fields import validate_config
from bluenode.testing import NodeHarness
from homekit_bridge import HomeKitBridge


@pytest.fixture(autouse=True)
def _no_mdns(monkeypatch):
    monkeypatch.setattr(HomeKitBridge, "ADVERTISE", False)
    monkeypatch.setattr(HomeKitBridge, "SETTLE", 0.0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def wait_for(pred, timeout: float = 3.0) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


def test_describes_as_a_home_server() -> None:
    d = HomeKitBridge.describe()
    assert (d["type"], d["category"], d["provides"]) == ("homekit-bridge", "home", "homekit")


async def test_start_shows_the_setup_code_and_keeps_it() -> None:
    h = NodeHarness(HomeKitBridge, {"port": free_port()}, node_id="br1")
    await h.node.on_start()
    await wait_for(lambda: (h.status or {}).get("text", "").startswith("not paired — code "))
    code = h.status["text"].removeprefix("not paired — code ")
    stored = json.loads((h.node.data_dir("homekit") / "br1.json").read_text())
    assert stored["pincode"] == code
    await h.node.on_stop()
    assert not h.node.host.started


async def test_fixed_setup_code() -> None:
    h = NodeHarness(HomeKitBridge, {"port": free_port(), "setup_code": "111-22-333"})
    await h.node.on_start()
    await wait_for(lambda: h.status and h.status["text"] == "not paired — code 111-22-333")
    await h.node.on_stop()


@pytest.mark.parametrize("field, value", [("setup_code", "12345678"), ("port", 80), ("address", "not an ip")])
def test_bad_config(field, value) -> None:
    assert validate_config(HomeKitBridge, {field: value})


def test_name_is_the_bridge_name() -> None:
    assert homekit_bridge.bridge_name("") == "BlueNode"
    assert homekit_bridge.bridge_name("Maison") == "Maison"
