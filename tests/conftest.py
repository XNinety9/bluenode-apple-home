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
