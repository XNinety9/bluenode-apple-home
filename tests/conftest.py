"""Shared fixtures: a bridge host without mDNS, on a free port, with short settle and linger delays."""

from __future__ import annotations

import pytest

from bluenode_apple_home.hap import BridgeHost


@pytest.fixture
async def host(tmp_path):
    h = BridgeHost("Test", tmp_path, "b1", 0, None, advertise=False, settle=0.2, linger=0.2)
    await h.start()
    yield h
    await h.stop()


# ---- a started bridge node, and accessory nodes wired to it

import asyncio  # noqa: E402
import socket  # noqa: E402

from bluenode.testing import NodeHarness  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
async def bridge(monkeypatch):
    from homekit_bridge import HomeKitBridge

    monkeypatch.setattr(HomeKitBridge, "ADVERTISE", False)
    monkeypatch.setattr(HomeKitBridge, "SETTLE", 0.0)
    monkeypatch.setattr(HomeKitBridge, "LINGER", 0.1)
    h = NodeHarness(HomeKitBridge, {"port": free_port()}, node_id="bridge")
    await h.node.on_start()
    yield h.node
    await h.node.on_stop()


@pytest.fixture
async def wire(bridge):
    """wire(cls, config) -> a started harness of an accessory node using `bridge`."""
    started = []

    async def make(cls, config=None, node_id="acc1"):
        h = NodeHarness(cls, config or {}, node_id=node_id)
        h.node.servers["bridge"] = bridge
        await h.node.on_start()
        started.append(h)
        return h

    yield make
    for h in started:
        await h.node.on_stop()


def char(h, name, service=None):
    svc = h.node.acc.get_service(service or h.node.service_name())
    return svc.get_characteristic(name)
