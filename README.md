# BlueNode — Apple Home

HomeKit nodes for BlueNode: BlueNode becomes a bridge in the **Home** app, and each
accessory node is an accessory you can see, control with Siri and use in Home automations. Your home hub
(Apple TV, HomePod or iPad) keeps it reachable when you are away.

## Install

In BlueNode: **Manage palette** › **Install** › *From git*, give this repository's address,
`https://github.com/XNinety9/bluenode-apple-home` (a path to a local clone works too), check the preview (the code, and the Python
packages it installs: HAP-python and what it needs), then **Install**. The nodes appear in the palette's
**Home** category.

The Home app finds the bridge through mDNS on your local network:
- BlueNode and the iPhone must be on the **same network** (same Wi-Fi / VLAN, multicast allowed);
- in Docker, run BlueNode on the **host network**:
  `docker compose -f docker-compose.yml -f docker-compose.apple-home.yml up` (from BlueNode's folder).

## Pair

1. Drop a **HomeKit bridge** node (palette › Home), and accessory nodes; wire each accessory's **bridge**
   port (top) to the bridge's service port (bottom). Deploy.
2. The status under the bridge shows `not paired — code 123-45-678`.
3. In the Home app: **+** › **Add Accessory** › **More options…** › the bridge › type the code. Accept the
   "uncertified accessory" warning (every home-made bridge gets it).
4. Put the accessories in their rooms. The status turns green: `paired — N accessories`.

The pairing and the accessories' ids are kept in the project's `homekit/` folder (left out of git), so
rooms, names and automations survive restarts and redeploys.

## Nodes

| Node | In (`msg.payload`) | Out (a change made in Home) |
| ---- | ------------------ | --------------------------- |
| HomeKit bridge | — (server node: name, port 51826, setup code, address) | — |
| Switch, Outlet | `true` / `false` (`on`/`off`, `1`/`0`) | `true` / `false` |
| Light | `true` / `false`, or `{on, brightness, color_temperature, hue, saturation}` | `{brightness: 75}`… |
| Button | `"single"` / `"double"` / `"long"` → runs the Home automations of that press | — |
| Temperature | °C | — |
| Humidity | % | — |
| Light level | lux | — |
| Motion, Occupancy, Leak, Smoke | `true` / `false` (detected) | — |
| Contact | `true` closed / `false` open | — |
| Window covering | position 0–100 | the position asked |
| Thermostat | °C, or `{current, target, mode}` (`off`/`heat`/`cool`/`auto`) | `{target}` / `{mode}` |
| Lock | `true` locked / `false` | `true` lock / `false` unlock |
| Garage door | `open` / `closed` / `opening` / `closing` / `stopped` | `"open"` / `"closed"` |
| Fan | `true` / `false`, or `{on, speed}` | `{on}` / `{speed}` |
| HomeKit accessory | `{"<Characteristic>": value}` for any HomeKit service | `{"<Characteristic>": value}` |

Every accessory node also takes a dict of its HomeKit characteristic names (`{"On": true}` on a switch), and has
**Manufacturer**, **Model** and **Battery** options (with Battery: `{"BatteryLevel": 80, "StatusLowBattery": 0}`).
Output messages carry `msg.characteristic`, `msg.value` (the raw HomeKit value) and `msg.source = "homekit"`;
what the flow sends in never comes back out. A payload of the wrong shape is a node error (Catch node).

## Example flows

`examples/apple-home.yaml` is a flow tab to try every node with the Home app: a bridge, a switch, a
temperature sensor with a battery, a button with three presses, a door contact, a motion sensor, a
dimmable light, a blind / a lock / a garage door that answer what Home asks after a delay, a thermostat,
a fan and an air purifier (generic node). What Home asks shows in the **From Home** Debug node.

After installing the pack, copy the file into the project's `flows/` folder and restart BlueNode:

```bash
cp examples/apple-home.yaml <project>/flows/
```

Then pair the bridge (see above) and play with the inject buttons and the Home app.

## Troubleshooting

- **The bridge does not show in the Home app**: same network? Docker on the host network? A firewall
  letting TCP 51826 and mDNS (UDP 5353) in?
- **Status `port 51826 in use`**: another bridge (or another program) uses it: change the port.
- **Start again from scratch**: remove the bridge in the Home app, delete `homekit/<bridge node id>.*` in the
  project, restart BlueNode and pair again.

## Development

```bash
uv sync                 # BlueNode (../BlueNode/backend, editable), HAP-python, pytest
uv run pytest           # BLUENODE_OFFLINE=1 skips the install-as-a-pack test (it needs PyPI)
```

The pack is what BlueNode reads from the repository: `requirements.txt`, the package `bluenode_apple_home/`
(HAP glue, no node) and the node files at the root (`homekit_bridge.py`, `homekit_accessories.py`).
`pyproject.toml` and `tests/` are for development only.
