"""A HomeKit bridge run by HAP-python on BlueNode's event loop.

What the Home app must find again after every restart is kept in the node's data folder:
- `<key>.state` — HAP-python's own state (the bridge's keys, the paired iPhones…);
- `<key>.json` — ours: the setup code (HAP-python does not keep it) and the accessory id of each node.

Two delays protect the rooms and automations the user made in Home, which Home forgets as soon as an
accessory is missing from the bridge:
- **settle**: the HAP server starts once every accessory seen last time is attached again (or after
  `settle` seconds), so Home never sees a half-empty bridge at start-up;
- **linger**: a detached accessory stays on the bridge `linger` seconds, so a redeploy (the node stops,
  then starts again) changes nothing in Home. Stopping the bridge removes nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pyhap import util
from pyhap.accessory import Accessory, Bridge
from pyhap.accessory_driver import AccessoryDriver

log = logging.getLogger("bluenode.homekit")

PINCODE_RE = re.compile(r"^\d{3}-\d{2}-\d{3}$")
StatusFn = Callable[[str, str], None]  # (color, text)


def _private(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.chmod(path, 0o600)


class _Driver(AccessoryDriver):
    """HAP-python's driver, with its state file private and pairing changes reported."""

    on_pairing: Callable[[], None] | None = None

    def persist(self) -> None:
        super().persist()
        _private(Path(self.persist_file))

    def async_persist(self) -> None:
        super().async_persist()
        _private(Path(self.persist_file))

    def pair(self, *args: Any, **kwargs: Any) -> Any:
        result = super().pair(*args, **kwargs)
        if self.on_pairing:
            self.loop.call_soon(self.on_pairing)
        return result

    def unpair(self, *args: Any, **kwargs: Any) -> Any:
        result = super().unpair(*args, **kwargs)
        if self.on_pairing:
            self.loop.call_soon(self.on_pairing)
        return result


class BridgeHost:
    def __init__(
        self,
        name: str,
        folder: Path,
        key: str,
        port: int,
        pincode: str | None,
        address: str | None = None,
        advertise: bool = True,
        on_status: StatusFn | None = None,
        settle: float = 10.0,
        linger: float = 10.0,
    ) -> None:
        if pincode and not PINCODE_RE.match(pincode):
            raise ValueError("the setup code is 8 digits written 123-45-678")
        self.name, self.folder, self.key, self.port = name, Path(folder), key, port
        self.address = address or None
        self.advertise, self.settle, self.linger = advertise, settle, linger
        self._wanted_pincode = pincode or None
        self._on_status = on_status or (lambda _c, _t: None)
        self.pincode = ""
        self.aids: dict[str, int] = {}
        self.next_aid = 2  # never reused: a controller that missed a removal must not see another accessory there
        self.driver: _Driver | None = None
        self.bridge: Bridge | None = None
        self.started = False
        self._known: set[str] = set()
        self._attached: dict[str, Accessory] = {}  # node id -> accessory on the bridge
        self._removals: dict[str, asyncio.TimerHandle] = {}
        self._ready = asyncio.Event()
        self._starter: asyncio.Task[None] | None = None

    # ---- files

    @property
    def ids_file(self) -> Path:
        return self.folder / f"{self.key}.json"

    def _load_ids(self) -> None:
        try:
            data = json.loads(self.ids_file.read_text())
        except (OSError, ValueError):
            data = {}
        aids = data.get("aids") if isinstance(data, dict) else None
        self.aids = {str(k): int(v) for k, v in aids.items()} if isinstance(aids, dict) else {}
        stored_next = data.get("next_aid") if isinstance(data, dict) else None
        self.next_aid = max([stored_next if isinstance(stored_next, int) else 2, 2, *(a + 1 for a in self.aids.values())])
        stored = data.get("pincode") if isinstance(data, dict) else None
        self.pincode = self._wanted_pincode or (stored if isinstance(stored, str) and PINCODE_RE.match(stored) else "")
        if not self.pincode:
            self.pincode = util.generate_pincode().decode()

    def _save_ids(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.ids_file.with_suffix(".json.tmp")
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)  # private from the first byte: it holds the code
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"pincode": self.pincode, "aids": self.aids, "next_aid": self.next_aid}, indent=1))
        tmp.replace(self.ids_file)

    # ---- life

    async def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._load_ids()
        self._save_ids()
        self.driver = _Driver(
            port=self.port,
            persist_file=str(self.folder / f"{self.key}.state"),
            pincode=self.pincode.encode(),
            loop=asyncio.get_running_loop(),
            address=self.address,
            advertise=self.advertise,
        )
        self.driver.state.pincode = self.pincode.encode()  # a state file from before keeps the code we chose
        self.driver.on_pairing = self._report
        _private(Path(self.driver.persist_file))
        self.bridge = Bridge(self.driver, self.name)
        self.driver.add_accessory(self.bridge)
        self._known = set(self.aids)
        self._check_ready()
        self._on_status("yellow", "starting…")
        self._starter = asyncio.get_running_loop().create_task(self._start_server())

    async def _start_server(self) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ready.wait(), self.settle)
        assert self.driver is not None
        # accessories of last time that did not come back are gone (removed while BlueNode was stopped)
        gone = [node_id for node_id in self.aids if node_id not in self._attached]
        for node_id in gone:
            del self.aids[node_id]
        if gone:
            self._save_ids()
        try:
            await self.driver.async_start()
        except Exception as exc:  # noqa: BLE001 - shown under the node
            await self._cleanup_failed_start()
            if isinstance(exc, OSError) and exc.errno == errno.EADDRINUSE:
                text = f"port {self.port} in use"
                log.warning("HomeKit bridge %s: %s", self.name, text)
            else:
                text = f"cannot start: {exc}"
                log.exception("HomeKit bridge %s", self.name)
            self._on_status("red", text)
            return
        self.started = True
        self._report()

    async def _cleanup_failed_start(self) -> None:
        """A start that failed half-way (mDNS after the server was listening): give the port back."""
        driver = self.driver
        if driver is None:
            return
        if getattr(driver.http_server, "server", None) is not None:
            with contextlib.suppress(Exception):
                driver.http_server.async_stop()
        if driver.advertiser is not None:
            with contextlib.suppress(Exception):
                await driver.advertiser.async_close()
            driver.advertiser = None

    def _sync_config(self) -> None:
        """When what Home caches changed (accessories, services, characteristics, their ids), tell it."""
        if not self.started or self.driver is None:
            return
        current = self.driver.accessories_hash
        if self.driver.state.accessories_hash != current:
            self.driver.state.accessories_hash = current
            self.driver.config_changed()
        self._report()

    async def stop(self) -> None:
        for handle in self._removals.values():
            handle.cancel()  # stopping removes nothing: Home keeps the accessories
        self._removals.clear()
        if self._starter is not None and not self._starter.done():
            self._starter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._starter
        if self.started and self.driver is not None:
            self.started = False
            with contextlib.suppress(Exception):
                await self.driver.async_stop()

    # ---- status

    @property
    def paired(self) -> bool:
        return bool(self.driver and self.driver.state.paired)

    def _report(self) -> None:
        if not self.started:
            return
        if self.paired:
            n = len(self.bridge.accessories) if self.bridge else 0
            self._on_status("green", f"paired — {n} accessor{'y' if n == 1 else 'ies'}")
        else:
            self._on_status("yellow", f"not paired — code {self.pincode}")

    # ---- accessories

    def _check_ready(self) -> None:
        if self._known <= set(self._attached):
            self._ready.set()

    def _new_aid(self) -> int:
        used = set(self.aids.values())
        aid = next(a for a in range(self.next_aid, 1 << 31) if a != 7 and a not in used)  # HAP-python skips 7
        self.next_aid = aid + 1
        return aid

    def attach(self, node_id: str, factory: Callable[[AccessoryDriver, int], Accessory]) -> Accessory:
        """Put the accessory of node `node_id` on the bridge (with the id it had before) and return it."""
        assert self.driver is not None and self.bridge is not None, "start the bridge first"
        pending = self._removals.pop(node_id, None)
        if pending is not None:
            pending.cancel()
        new_aid = node_id not in self.aids
        if new_aid:
            self.aids[node_id] = self._new_aid()
            self._save_ids()
        aid = self.aids[node_id]
        acc = factory(self.driver, aid)
        old = self._attached.get(node_id)
        if old is not None:
            _copy_values(old, acc)
            self.bridge.accessories.pop(aid, None)
        self.bridge.add_accessory(acc)
        self._attached[node_id] = acc
        self._sync_config()
        self._check_ready()
        return acc

    def detach(self, node_id: str) -> None:
        """The node stopped: its accessory leaves the bridge `linger` seconds later, unless it comes back."""
        if node_id not in self._attached or node_id in self._removals:
            return
        self._removals[node_id] = asyncio.get_running_loop().call_later(self.linger, self._remove, node_id)

    def _remove(self, node_id: str) -> None:
        self._removals.pop(node_id, None)
        acc = self._attached.pop(node_id, None)
        if acc is None or self.bridge is None or self.driver is None:
            return
        self.bridge.accessories.pop(acc.aid, None)
        self.aids.pop(node_id, None)
        self._save_ids()
        self._sync_config()


def _copy_values(old: Accessory, new: Accessory) -> None:
    """Keep what Home showed (a light's brightness…) when a node restarts with an accessory of the same kind."""
    for service in new.services:
        if service.display_name == "AccessoryInformation":
            continue  # the name, model… come from the node's new config
        before = old.get_service(service.display_name)
        if before is None:
            continue
        for char in service.characteristics:
            with contextlib.suppress(Exception):
                prev = before.get_characteristic(char.display_name)
                char.set_value(prev.value, should_notify=False)
