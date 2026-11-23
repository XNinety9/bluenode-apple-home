"""The HAP bridge host: setup code, stable accessory ids, waiting for accessories, removal delay."""

from __future__ import annotations

import asyncio
import json
import re
import socket
import stat

import pytest
from pyhap.accessory import Accessory

from bluenode_apple_home.hap import BridgeHost


def switch(name: str = "Switch"):
    def factory(driver, aid):
        acc = Accessory(driver, name, aid=aid)
        acc.add_preload_service("Switch")
        return acc

    return factory


def light(driver, aid):
    acc = Accessory(driver, "Light", aid=aid)
    acc.add_preload_service("Lightbulb", chars=["Brightness"])
    return acc


async def wait_for(pred, timeout: float = 3.0) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.02)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


async def test_pincode_generated_once_and_kept(tmp_path) -> None:
    a = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await a.start()
    await a.stop()
    b = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await b.start()
    await b.stop()
    assert re.fullmatch(r"\d{3}-\d{2}-\d{3}", a.pincode)
    assert a.pincode == b.pincode
    for name in ("b1.json", "b1.state"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600, name


async def test_given_pincode_is_used(tmp_path) -> None:
    h = BridgeHost("T", tmp_path, "b1", 0, "123-45-678", advertise=False, settle=0)
    await h.start()
    assert h.pincode == "123-45-678"
    assert h.driver.state.pincode == b"123-45-678"
    await h.stop()


@pytest.mark.parametrize("bad", ["12345678", "123-456-78", "abc-de-fgh"])
def test_bad_pincode(tmp_path, bad) -> None:
    with pytest.raises(ValueError, match="123-45-678"):
        BridgeHost("T", tmp_path, "b1", 0, bad, advertise=False)


async def test_aid_stable_across_restart(tmp_path) -> None:
    a = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await a.start()
    assert a.attach("n1", switch()).aid == 2
    assert a.attach("n2", switch()).aid == 3
    await a.stop()
    b = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=5)
    await b.start()
    assert b.attach("n2", switch()).aid == 3
    assert b.attach("n1", switch()).aid == 2
    await b.stop()


async def test_server_waits_for_known_accessories(tmp_path) -> None:
    a = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await a.start()
    a.attach("n1", switch())
    await wait_for(lambda: a.started)
    await a.stop()

    b = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=30)
    await b.start()
    await asyncio.sleep(0.1)
    assert not b.started  # n1 is expected
    b.attach("n1", switch())
    await wait_for(lambda: b.started)
    await b.stop()


async def test_server_starts_after_settle_without_them(tmp_path) -> None:
    a = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await a.start()
    a.attach("n1", switch())
    await a.stop()
    b = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0.2)
    await b.start()
    await wait_for(lambda: b.started)
    await b.stop()


async def test_reattach_within_linger_keeps_aid_and_config(host, monkeypatch) -> None:
    await wait_for(lambda: host.started)
    acc = host.attach("n1", switch())
    calls = []
    monkeypatch.setattr(host.driver, "config_changed", lambda: calls.append(1))
    acc.get_service("Switch").get_characteristic("On").set_value(True)
    host.detach("n1")
    again = host.attach("n1", switch())
    assert again.aid == acc.aid
    assert host.bridge.accessories[acc.aid] is again
    assert again.get_service("Switch").get_characteristic("On").value is True  # values carried over
    await asyncio.sleep(0.4)  # past the linger delay: still there
    assert acc.aid in host.bridge.accessories
    assert calls == []


async def test_reattach_with_other_services_changes_config(host, monkeypatch) -> None:
    await wait_for(lambda: host.started)
    host.attach("n1", switch())
    calls = []
    monkeypatch.setattr(host.driver, "config_changed", lambda: calls.append(1))
    host.detach("n1")
    host.attach("n1", light)
    assert calls == [1]


async def test_new_accessory_after_start_changes_config(host, monkeypatch) -> None:
    await wait_for(lambda: host.started)
    calls = []
    monkeypatch.setattr(host.driver, "config_changed", lambda: calls.append(1))
    host.attach("n1", switch())
    assert calls == [1]


async def test_detach_removes_after_linger(host, tmp_path, monkeypatch) -> None:
    await wait_for(lambda: host.started)
    acc = host.attach("n1", switch())
    calls = []
    monkeypatch.setattr(host.driver, "config_changed", lambda: calls.append(1))
    host.detach("n1")
    await wait_for(lambda: acc.aid not in host.bridge.accessories)
    assert calls == [1]
    assert "n1" not in json.loads((tmp_path / "b1.json").read_text())["aids"]


async def test_stop_removes_nothing(tmp_path) -> None:
    h = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0, linger=0.1)
    await h.start()
    h.attach("n1", switch())
    h.detach("n1")  # the node stops first, then the bridge
    await h.stop()
    await asyncio.sleep(0.2)
    assert json.loads((tmp_path / "b1.json").read_text())["aids"] == {"n1": 2}


async def test_port_in_use_status(tmp_path) -> None:
    port = free_port()
    seen = []
    a = BridgeHost("A", tmp_path / "a", "b1", port, None, advertise=False, settle=0)
    b = BridgeHost("B", tmp_path / "b", "b1", port, None, advertise=False, settle=0, on_status=lambda c, t: seen.append((c, t)))
    await a.start()
    await wait_for(lambda: a.started)
    await b.start()
    await wait_for(lambda: ("red", f"port {port} in use") in seen)
    assert not b.started
    await b.stop()
    await a.stop()


async def test_status_says_code_until_paired(tmp_path) -> None:
    seen = []
    h = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0, on_status=lambda c, t: seen.append((c, t)))
    await h.start()
    await wait_for(lambda: h.started)
    assert seen[-1] == ("yellow", f"not paired — code {h.pincode}")
    await h.stop()


# ---- review fixes


def named(name: str, model: str):
    def factory(driver, aid):
        acc = Accessory(driver, name, aid=aid)
        acc.set_info_service(model=model)
        acc.add_preload_service("Switch")
        return acc

    return factory


def purifier(chars):
    def factory(driver, aid):
        acc = Accessory(driver, "Purifier", aid=aid)
        acc.add_preload_service("AirPurifier", chars=chars)
        return acc

    return factory


async def test_rename_on_redeploy_reaches_home(host) -> None:
    await wait_for(lambda: host.started)
    host.attach("n1", named("Old", "X1"))
    host.detach("n1")
    acc = host.attach("n1", named("New", "X2"))
    info = acc.get_service("AccessoryInformation")
    assert (info.get_characteristic("Name").value, info.get_characteristic("Model").value) == ("New", "X2")


async def test_reordered_characteristics_change_config(host, monkeypatch) -> None:
    await wait_for(lambda: host.started)
    host.attach("n1", purifier(["RotationSpeed", "LockPhysicalControls"]))
    calls = []
    monkeypatch.setattr(host.driver, "config_changed", lambda: calls.append(1))
    host.detach("n1")
    host.attach("n1", purifier(["LockPhysicalControls", "RotationSpeed"]))
    assert calls == [1]  # the iids moved: Home must fetch the accessories again


async def test_failed_start_frees_the_port(tmp_path, monkeypatch) -> None:
    import pyhap.accessory_driver as driver_module

    def broken(*_args, **_kwargs):
        raise OSError("no multicast")

    port = free_port()
    seen = []
    monkeypatch.setattr(driver_module, "AsyncZeroconf", broken)
    a = BridgeHost("A", tmp_path / "a", "b1", port, None, advertise=True, settle=0, on_status=lambda c, t: seen.append((c, t)))
    await a.start()
    await wait_for(lambda: seen and seen[-1][0] == "red")
    await a.stop()
    monkeypatch.undo()
    b = BridgeHost("B", tmp_path / "b", "b1", port, None, advertise=False, settle=0)
    await b.start()
    await wait_for(lambda: b.started)  # the port was given back
    await b.stop()


async def test_accessories_gone_while_stopped_are_forgotten(tmp_path) -> None:
    a = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await a.start()
    a.attach("n1", switch())
    a.attach("n2", switch())
    await a.stop()
    b = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0.2)
    await b.start()
    b.attach("n1", switch())
    await wait_for(lambda: b.started)
    assert json.loads((tmp_path / "b1.json").read_text())["aids"] == {"n1": 2}
    await b.stop()


async def test_aids_are_never_reused(tmp_path) -> None:
    h = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0, linger=0.05)
    await h.start()
    h.attach("n1", switch())
    h.attach("n2", switch())  # aid 3
    h.detach("n2")
    await wait_for(lambda: "n2" not in h.aids)
    assert h.attach("n3", switch()).aid == 4
    await h.stop()
    again = BridgeHost("T", tmp_path, "b1", 0, None, advertise=False, settle=0)
    await again.start()
    assert again.attach("n4", switch()).aid == 5
    await again.stop()
