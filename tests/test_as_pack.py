"""The repository installs as a BlueNode pack (Manage palette › Install from git), with its dependencies."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bluenode.registry import default_registry
from bluenode.server import create_app

REPO = Path(__file__).resolve().parent.parent
TYPES = {
    "homekit-bridge", "homekit-switch", "homekit-outlet", "homekit-button", "homekit-temperature", "homekit-humidity",
    "homekit-light-level", "homekit-motion", "homekit-occupancy", "homekit-contact", "homekit-leak", "homekit-smoke",
    "homekit-light", "homekit-window-covering", "homekit-thermostat", "homekit-lock", "homekit-garage-door",
    "homekit-fan", "homekit-accessory",
}

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(os.environ.get("BLUENODE_OFFLINE") == "1", reason="needs PyPI"),
]


@pytest.fixture
def as_on_a_server(monkeypatch):
    """A BlueNode server does not have this repository on its path (pytest puts it there for the tests)."""
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p or ".").resolve() != REPO])
    for name in [m for m in sys.modules if m.split(".")[0] in ("bluenode_apple_home", "homekit_bridge", "homekit_accessories")]:
        monkeypatch.delitem(sys.modules, name)


def test_installs_as_a_pack(tmp_path, as_on_a_server) -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    project = tmp_path / "project"
    project.mkdir()
    before = list(sys.path)
    try:
        with TestClient(create_app(project, registry=default_registry())) as client:
            r = client.post("/api/palette/install/git/preview", json={"url": str(REPO)})
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["commit"] == head
            assert p["ok"], [(f["file"], f["problems"]) for f in p["files"] if not f["ok"]]
            assert p["requirements"] == ["HAP-python<6,>=5.2"]
            assert p["package"] == "bluenode_apple_home"
            assert sorted(f["file"] for f in p["files"]) == ["homekit_accessories.py", "homekit_bridge.py"]
            assert client.post("/api/palette/install/git", json={"token": p["token"]}).status_code == 200
            types = {t["type"]: t for t in client.get("/api/node-types").json()}
            assert TYPES <= set(types)
            assert {types[t]["category"] for t in TYPES} == {"home"}
            assert all(types[t]["source"] == "pack" for t in TYPES)
    finally:
        sys.path[:] = before
