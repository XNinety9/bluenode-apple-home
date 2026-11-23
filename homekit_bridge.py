"""HomeKit bridge: BlueNode in the Home app (Apple TV, HomePod or iPad as the home hub)."""

from __future__ import annotations

from typing import ClassVar

from bluenode.node import Field, Server

from bluenode_apple_home.hap import BridgeHost


def bridge_name(name: str) -> str:
    return name.strip() or "BlueNode"


class HomeKitBridge(Server):
    """Shows BlueNode in the Home app as a bridge, with the accessories wired to it.

    Wire its service port to the **bridge** port of the HomeKit accessory nodes (Switch, Light,
    Temperature…). Each one becomes an accessory of this bridge in the Home app.

    ### Pairing
    1. Deploy. The status under the node shows `not paired — code 123-45-678`.
    2. In the Home app on the iPhone: **+** › **Add Accessory** › **More options…**, pick the bridge
       (its name), then type the code.
    3. The status turns green: `paired — N accessories`. Put the accessories in their rooms.

    The iPhone and BlueNode must be on the same network. In Docker, run BlueNode on the host network
    (`docker-compose.apple-home.yml`): the Home app finds the bridge through mDNS.

    ### Configuration
    - **Name** — the bridge's name in the Home app. Default `BlueNode`.
    - **Port** — the TCP port of the HomeKit server (1024 to 65535). Default `51826`; two bridges need two ports.
    - **Setup code** — the code typed in the Home app, as `123-45-678`. Empty (default): one is made up once
      and kept.
    - **Address** — the IPv4 address announced to the Home app, when the machine has several. Empty: chosen
      automatically.

    ### Details
    - The pairing and the accessories' ids are kept in the project folder `homekit/` (not in git): the
      accessories keep their rooms and automations across restarts. Delete that folder's files of this node
      (named after its id) to pair again from scratch, after removing the bridge in the Home app.
    - After a start, the bridge waits up to 10 seconds for the accessories it had before, so the Home app
      never sees them missing. An accessory node removed from the flows leaves the Home app 10 seconds after
      the deploy.
    """

    type = "homekit-bridge"
    label = "HomeKit bridge"
    icon = "house"
    category = "home"
    provides = "homekit"

    ADVERTISE: ClassVar[bool] = True  # tests: no mDNS
    SETTLE: ClassVar[float] = 10.0
    LINGER: ClassVar[float] = 10.0

    class Config(Server.Config):
        port: int = Field(default=51826, ge=1024, le=65535, title="Port")
        setup_code: str = Field(
            default="",
            title="Setup code",
            regex=r"(\d{3}-\d{2}-\d{3})?",
            hint="123-45-678, or empty: made up once and kept",
        )
        address: str = Field(default="", title="Address", check="ipv4", hint="empty: chosen automatically")

    host: BridgeHost | None = None

    async def on_start(self) -> None:
        c = self.config
        self.host = BridgeHost(
            bridge_name(c.name),
            self.data_dir("homekit"),
            self.id,
            c.port,
            c.setup_code or None,
            address=c.address or None,
            advertise=self.ADVERTISE,
            on_status=self.status,
            settle=self.SETTLE,
            linger=self.LINGER,
        )
        await self.host.start()

    async def on_stop(self) -> None:
        if self.host is not None:
            await self.host.stop()
