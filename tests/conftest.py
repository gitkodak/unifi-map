"""Synthetic controller payloads.

A plausible generic small site, deliberately not modelled on any real network:
invented MACs, RFC 1918 addresses that match the shipped demo dataset, and no
credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from unifi_map import config
from unifi_map.client import Snapshot


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch, tmp_path):
    """Run every test as though the machine had no unifi-map configuration.

    Settings can arrive from three places the test never mentions: real
    environment variables, a credential file found by searching, and a config
    file in the user's home directory. Any of them can change what a parser
    returns, so without this the suite passes or fails according to whose
    machine it runs on.

    This is not hypothetical. `TestDirectoriesFromTheEnvironment` carries its
    own copy of the first two, added after a developer with `UNIFI_CACHE_DIR`
    in a real credential file failed a test that had nothing to do with
    directories. That fix was per-class; this one is the class of problem,
    which is why the local copy can stay without conflicting: an autouse
    fixture runs first, and a test setting a variable afterwards still wins.

    Emptying the search path matters more than it looks. Pointing the env-file
    variable at a nonexistent file is not enough, because the search continues
    past a missing candidate to `./.env` and then the home config.

    Only *implicit* discovery is removed. A test that points `UNIFI_MAP_ENV` or
    `UNIFI_MAP_CONFIG` at a file it wrote is exercising the real feature and
    must still work, so both stubs honour their variable and fall back to
    nothing rather than to the user's home directory.
    """

    def env_files() -> list[Path]:
        named = os.environ.get(config.ENV_FILE_VAR, "").strip()
        return [Path(named).expanduser()] if named else []

    def config_file() -> Path:
        named = os.environ.get(config.CONFIG_FILE_VAR, "").strip()
        return Path(named).expanduser() if named else tmp_path / "absent.toml"

    monkeypatch.setattr(config, "default_env_files", env_files)
    monkeypatch.setattr(config, "default_config_file", config_file)
    for name in list(config._SETTING_VARS.values()) + list(config._LEGACY_SETTING_VARS.values()):
        monkeypatch.delenv(name, raising=False)
    for name in (config.ENV_FILE_VAR, config.CONFIG_FILE_VAR):
        monkeypatch.delenv(name, raising=False)


GATEWAY_MAC = "aa:bb:cc:00:00:01"
SWITCH_MAC = "aa:bb:cc:00:00:02"
AP_MAC = "aa:bb:cc:00:00:03"
SPARE_SWITCH_MAC = "aa:bb:cc:00:00:04"


def _wrap(records: list[dict]) -> dict:
    return {"meta": {"rc": "ok"}, "data": records}


@pytest.fixture
def networkconf() -> dict:
    return _wrap(
        [
            {"_id": "net1", "name": "lan", "vlan": 1, "ip_subnet": "10.0.0.1/24"},
            {"_id": "net2", "name": "servers", "vlan": 2, "ip_subnet": "10.0.20.1/24"},
            {"_id": "net33", "name": "iot", "vlan": 33, "ip_subnet": "10.0.30.1/24"},
        ]
    )


@pytest.fixture
def devices() -> dict:
    return _wrap(
        [
            {
                "mac": GATEWAY_MAC,
                "name": "gateway",
                "type": "udm",
                "model": "UDMPROMAX",
                "ip": "10.0.0.1",
                "state": 1,
            },
            {
                "mac": SWITCH_MAC,
                "name": "Core Switch",
                "type": "usw",
                "model": "USWProHD24PoE",
                "ip": "10.0.0.2",
                "state": 1,
                "uplink": {"uplink_mac": GATEWAY_MAC, "uplink_remote_port": 9, "type": "wire"},
            },
            {
                "mac": AP_MAC,
                "name": "Living Room",
                "type": "uap",
                "model": "U7PRO",
                "ip": "10.0.0.3",
                "state": 1,
                "uplink": {"uplink_mac": SWITCH_MAC, "uplink_remote_port": 5, "type": "wire"},
            },
            {
                # The spare USW-Enterprise-24-PoE: adopted but unplugged. Must
                # render as offline rather than vanish from the map.
                "mac": SPARE_SWITCH_MAC,
                "name": "Retired Switch",
                "type": "usw",
                "model": "USWEnterprise24PoE",
                "state": 0,
            },
        ]
    )


@pytest.fixture
def clients() -> dict:
    return _wrap(
        [
            {
                "mac": "dd:ee:ff:00:00:01",
                "name": "nas",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 12,
                "ip": "10.0.20.10",
                "network_id": "net2",
            },
            {
                "mac": "dd:ee:ff:00:00:02",
                "hostname": "tuner",
                "is_wired": True,
                "sw_mac": SWITCH_MAC,
                "sw_port": 14,
                "ip": "10.0.30.12",
                "network_id": "net33",
            },
            {
                "mac": "dd:ee:ff:00:00:03",
                "hostname": "phone",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "essid": "test-wifi",
                "radio_name": "ra0",
                "ip": "10.0.0.51",
                "network_id": "net1",
            },
            {
                # No hostname: must fall back to OUI + MAC tail, not a bare MAC.
                "mac": "dd:ee:ff:00:00:04",
                "oui": "Espressif",
                "is_wired": False,
                "ap_mac": AP_MAC,
                "essid": "test-iot",
                "radio": "ng",
                "ip": "10.0.30.44",
                "network_id": "net33",
            },
        ]
    )


@pytest.fixture
def snapshot(devices: dict, clients: dict, networkconf: dict) -> Snapshot:
    return Snapshot(
        payloads={
            "device": devices,
            "client_active": clients,
            "networkconf": networkconf,
        }
    )


@pytest.fixture
def png_bytes():
    """Factory for a real in-memory PNG of a given size."""

    def make(width: int, height: int) -> bytes:
        from io import BytesIO

        from PIL import Image

        buffer = BytesIO()
        Image.new("RGBA", (width, height), (10, 120, 200, 255)).save(buffer, format="PNG")
        return buffer.getvalue()

    return make


@pytest.fixture
def fake_icon(tmp_path, png_bytes):
    """A cached-artwork stand-in that needs no network."""
    from unifi_map.assets import IconAsset

    path = tmp_path / "icons" / "fake.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(64, 24))
    return IconAsset(path=path, width=64, height=24)
