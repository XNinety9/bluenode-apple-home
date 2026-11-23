"""What every HomeKit accessory node shares: its accessory on the bridge, values both ways.

A node subclass names its HAP service (`service`), the optional characteristics it adds, and two
conversions: `to_chars` (the simple payload of a flow → characteristic values) and `to_payload` (a value
written from the Home app → the simple payload). A dict whose keys are characteristic names sets them
directly, on every node.
"""

from __future__ import annotations

from typing import Any, ClassVar

from bluenode.node import Field, Msg, Node, SendFn
from pyhap.accessory import Accessory
from pyhap.accessory_driver import AccessoryDriver
from pyhap.characteristic import HAP_FORMAT_BOOL, HAP_FORMAT_NUMERICS, HAP_FORMAT_STRING
from pyhap.const import CATEGORY_OTHER
from pyhap.service import Service

NO_BRIDGE = "connect a HomeKit bridge"
BATTERY = "BatteryService"
TRUE = {"true", "on", "1", "yes"}
FALSE = {"false", "off", "0", "no"}


def as_bool(value: Any) -> bool:
    """`true/false`, `1/0`, `"on"/"off"`, `"yes"/"no"` (any case). ValueError otherwise."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in TRUE | FALSE:
        return value.strip().lower() in TRUE
    raise ValueError(f"expected true or false (or on / off, 1 / 0), got {value!r}")


def as_number(value: Any) -> float:
    """A number, or a string holding one. ValueError otherwise."""
    if isinstance(value, bool):
        raise ValueError(f"expected a number, got {value!r}")
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            pass
    raise ValueError(f"expected a number, got {value!r}")


def friendly(payload: Any, keys: dict[str, str], what: str) -> dict[str, Any]:
    """A dict of friendly keys (`{"on": true, "brightness": 40}`) → characteristic names. ValueError on others."""
    if not isinstance(payload, dict):
        raise ValueError(f"expected {what}, got {payload!r}")
    unknown = [str(k) for k in payload if k not in keys]
    if unknown:
        raise ValueError(f"{', '.join(unknown)}: not a setting of this accessory (it takes {', '.join(keys)})")
    return {keys[k]: v for k, v in payload.items()}


def as_choice(value: Any, choices: dict[str, int], what: str) -> int:
    key = str(value).strip().lower()
    if key not in choices:
        names = list(choices)
        raise ValueError(f"expected {what}: {', '.join(names[:-1])} or {names[-1]}, got {value!r}")
    return choices[key]


class AccessoryNode(Node):
    """Base of the HomeKit accessory nodes (no `type`: not a node itself)."""

    category = "home"
    uses: ClassVar[dict[str, str]] = {"bridge": "homekit"}

    service: ClassVar[str] = ""  # the HAP service, e.g. "Switch"
    characteristics: ClassVar[list[str]] = []  # optional characteristics added to it
    hap_category: ClassVar[int] = CATEGORY_OTHER

    class Config(Node.Config):
        manufacturer: str = Field(default="BlueNode", title="Manufacturer", max_length=64)
        model: str = Field(default="", title="Model", max_length=64)
        battery: bool = Field(default=False, title="Battery")

    acc: Accessory | None = None
    _host: Any = None
    _error: str | None = None  # why there is no accessory (shown in the status, raised on messages)

    # ---- what subclasses change

    def service_name(self) -> str:
        return self.service

    def optional_chars(self) -> list[str]:
        return list(self.characteristics)

    def setup(self, service: Service) -> None:
        """Adjust the service once created (ranges of values…)."""

    def to_chars(self, payload: Any) -> dict[str, Any]:
        """The simple payload of a flow → characteristic values."""
        if isinstance(payload, dict):
            unknown = [k for k in payload if self._char(k) is None]
            raise ValueError(f"unknown characteristic {', '.join(map(str, unknown))} for {self.service_name()}")
        raise ValueError(f"expected a dict of characteristics, got {payload!r}")

    def to_payload(self, char: str, value: Any) -> Any:
        """A value written from the Home app → the payload sent by the node."""
        return value

    # ---- life

    def check(self) -> str | None:
        """Why this node cannot make its accessory (its config), or None."""
        return None

    async def on_start(self) -> None:
        self._error = self.check()
        if self._error:
            self.status("red", self._error)
            return
        host = getattr(self.server("bridge"), "host", None)
        if host is None or host.bridge is None:
            self._error = NO_BRIDGE
            self.status("red", NO_BRIDGE)
            return
        self._host = host
        self.acc = host.attach(self.id, self._build)

    async def on_stop(self) -> None:
        if self._host is not None:
            self._host.detach(self.id)
            self._host = None

    def _build(self, driver: AccessoryDriver, aid: int) -> Accessory:
        acc = Accessory(driver, self.config.name or self.label, aid=aid)
        acc.category = self.hap_category
        acc.set_info_service(manufacturer=self.config.manufacturer, model=self.config.model or self.label, serial_number=self.id)
        service = acc.add_preload_service(self.service_name(), chars=self.optional_chars() or None)
        self.setup(service)
        if self.config.battery:
            acc.add_preload_service(BATTERY)
        for svc in acc.services:
            if svc.display_name == "AccessoryInformation":
                continue
            for char in svc.characteristics:
                if "pw" in char.properties.get("Permissions", []):
                    char.setter_callback = self._writer(char.display_name)
        return acc

    def _writer(self, name: str):  # noqa: ANN202
        def written(value: Any) -> None:  # called by HAP-python, on the event loop
            msg = self.new_message(
                payload=self.to_payload(name, value),
                topic=self.config.name,
                characteristic=name,
                value=value,
                source="homekit",
            )
            self.create_task(self.send(msg))

        return written

    # ---- values from the flow

    def _char(self, name: str) -> Any:
        if self.acc is None:
            return None
        names = [self.service_name()] + ([BATTERY] if self.config.battery else [])
        for svc_name in names:
            svc = self.acc.get_service(svc_name)
            if svc is None:
                continue
            for char in svc.characteristics:
                if char.display_name == name:
                    return char
        return None

    async def on_message(self, msg: Msg, send: SendFn) -> None:
        if self.acc is None:
            raise RuntimeError(self._error or NO_BRIDGE)
        payload = msg.get("payload")
        if isinstance(payload, dict) and payload and all(isinstance(k, str) and self._char(k) is not None for k in payload):
            values = payload
        else:
            values = self.to_chars(payload)
        checked = []
        for name, value in values.items():  # every value is checked before any is set: all or nothing
            char = self._char(name)
            if char is None:
                raise ValueError(f"unknown characteristic {name} for {self.service_name()}")
            checked.append((char, _coerce(char, value)))
        for char, value in checked:
            char.set_value(value)


def _coerce(char: Any, value: Any) -> Any:
    fmt = char.properties.get("Format")
    if fmt == HAP_FORMAT_BOOL:
        value = as_bool(value)
    elif fmt in HAP_FORMAT_NUMERICS:
        value = as_number(value)
    elif fmt == HAP_FORMAT_STRING:
        value = str(value)
    value = char.to_valid_value(value)
    try:
        char.valid_value_or_raise(value)
    except ValueError as exc:
        raise ValueError(f"{char.display_name}: {value!r} is not an accepted value") from exc
    return value
