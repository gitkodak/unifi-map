#!/usr/bin/env python3
"""Generate the demo snapshot in examples/demo/.

Everything here is invented: MACs use the locally-administered `02:` prefix,
addresses are RFC 1918, and no hostname belongs to a real person. The `sysid`
values ARE real, because they are what the tool joins against Ubiquiti's device
catalog to fetch artwork; with fake sysids the demo could not show icons.

Regenerate with:  python scripts/make_demo_snapshot.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "examples" / "demo"

# Real Ubiquiti fingerprint dev_ids, so the demo shows real client artwork too.
# These are plain integers from Ubiquiti's public fingerprint database.
DEV_ID = {
    "laptop": 4207,  # Generic Laptop
    "phone": 5346,  # Pixel 9
    "tv": 3166,  # Hisense Roku TV
    "speaker": 4425,  # Nest Audio
    "speaker_mini": 2028,  # Google Home Mini
    "thermostat": 2024,  # ecobee
    "dishwasher": 3622,  # Bosch dishwasher
    "streamer": 27,  # Roku device
    "tuner": 2799,  # HDHomeRun Connect Quatro
}

# Real UniFi hardware ids, so `--icons unifi` resolves artwork for the demo.
SYSID = {
    "udm_pro_max": 59954,
    "usw_pro_hd_24_poe": 60786,
    "usw_enterprise_24_poe": 60216,
    "usw_flex_mini": 60720,
    "u6_lite": 42514,
    "u7_pro": 42626,
    "ups_tower": 55843,
}

GW = "02:00:00:00:01:01"
CORE = "02:00:00:00:01:02"
RACK = "02:00:00:00:01:03"
DESK = "02:00:00:00:01:04"
AP_LIVING = "02:00:00:00:02:01"
AP_BEDROOM = "02:00:00:00:02:02"
AP_GARAGE = "02:00:00:00:02:03"
AP_OFFICE = "02:00:00:00:02:04"
UPS = "02:00:00:00:03:01"

NET_LAN = "net-lan"
NET_SERVERS = "net-servers"
NET_IOT = "net-iot"
NET_GUEST = "net-guest"


def device(mac, name, dtype, model, sysid, ip=None, uplink=None, port=None, state=1):
    entry = {
        "mac": mac,
        "name": name,
        "type": dtype,
        "model": model,
        "sysid": sysid,
        "state": state,
    }
    if ip:
        entry["ip"] = ip
    if uplink:
        entry["uplink"] = {"uplink_mac": uplink, "uplink_remote_port": port, "type": "wire"}
    return entry


def wired(mac, name, ip, network, sw_mac=None, sw_port=None, oui=None, dev_id=None):
    entry = {"mac": mac, "is_wired": True, "ip": ip, "network_id": network}
    if dev_id is not None:
        entry["dev_id"] = dev_id
    if name:
        entry["hostname"] = name
    if oui:
        entry["oui"] = oui
    # Omitting sw_mac models a client the controller cannot place (a VM or
    # container behind another host). The renderer anchors these to an explicit
    # "uplink not reported" node.
    if sw_mac:
        entry["sw_mac"] = sw_mac
        entry["sw_port"] = sw_port
    return entry


def wireless(mac, name, ip, network, ap_mac, essid, radio="ng", oui=None, dev_id=None, guest=False):
    entry = {
        "mac": mac,
        "is_wired": False,
        "is_guest": guest,
        "ip": ip,
        "network_id": network,
        "ap_mac": ap_mac,
        "essid": essid,
        "radio_name": radio,
    }
    if dev_id is not None:
        entry["dev_id"] = dev_id
    if name:
        entry["hostname"] = name
    if oui:
        entry["oui"] = oui
    return entry


def build() -> dict[str, dict]:
    devices = [
        device(GW, "gateway", "udm", "UDMPROMAX", SYSID["udm_pro_max"], "10.0.0.1"),
        device(
            CORE,
            "Core Switch",
            "usw",
            "USWED72",
            SYSID["usw_pro_hd_24_poe"],
            "10.0.0.2",
            GW,
            25,
        ),
        device(
            RACK,
            "Rack Switch",
            "usw",
            "US624P",
            SYSID["usw_enterprise_24_poe"],
            "10.0.0.3",
            CORE,
            24,
        ),
        device(
            DESK,
            "Desk Switch",
            "usw",
            "USMINI",
            SYSID["usw_flex_mini"],
            "10.0.0.4",
            CORE,
            12,
        ),
        device(
            AP_LIVING,
            "Living Room",
            "uap",
            "UAL6",
            SYSID["u6_lite"],
            "10.0.0.11",
            CORE,
            5,
        ),
        device(
            AP_BEDROOM,
            "Bedroom",
            "uap",
            "UAL6",
            SYSID["u6_lite"],
            "10.0.0.12",
            CORE,
            6,
        ),
        # One offline device, so the demo shows how those render.
        device(
            AP_GARAGE,
            "Garage",
            "uap",
            "UAL6",
            SYSID["u6_lite"],
            "10.0.0.13",
            CORE,
            7,
            state=0,
        ),
        device(
            AP_OFFICE,
            "Office",
            "uap",
            "U7PRO",
            SYSID["u7_pro"],
            "10.0.0.14",
            RACK,
            8,
        ),
        device(
            UPS,
            "Rack UPS",
            "usw",
            "USWDA23",
            SYSID["ups_tower"],
            "10.0.0.20",
            RACK,
            2,
        ),
    ]

    clients = [
        wired(
            "02:00:00:00:10:01", "nas", "10.0.20.10", NET_SERVERS, RACK, 1, dev_id=DEV_ID["tuner"]
        ),
        wired("02:00:00:00:10:02", "hypervisor", "10.0.20.11", NET_SERVERS, RACK, 3),
        # No sw_mac: a VM behind the hypervisor. Demonstrates the placeholder,
        # and is exactly the case the planned link overrides will fix.
        wired("02:00:00:00:10:03", "build-runner", "10.0.20.12", NET_SERVERS),
        wired("02:00:00:00:10:04", "reverse-proxy", "10.0.20.13", NET_SERVERS),
        wired(
            "02:00:00:00:11:01",
            "workstation",
            "10.0.0.50",
            NET_LAN,
            DESK,
            2,
            dev_id=DEV_ID["laptop"],
        ),
        wired("02:00:00:00:11:02", "printer", "10.0.0.51", NET_LAN, DESK, 3),
        wired("02:00:00:00:11:03", None, "10.0.0.52", NET_LAN, DESK, 4, oui="Intel Corporate"),
        wired(
            "02:00:00:00:12:01",
            "media-player",
            "10.0.0.53",
            NET_LAN,
            CORE,
            9,
            dev_id=DEV_ID["streamer"],
        ),
        wireless(
            "02:00:00:00:20:01",
            "phone-a",
            "10.0.0.101",
            NET_LAN,
            AP_LIVING,
            "demo-wifi",
            "ac",
            dev_id=DEV_ID["phone"],
        ),
        wireless(
            "02:00:00:00:20:02", "phone-b", "10.0.0.102", NET_LAN, AP_BEDROOM, "demo-wifi", "ac"
        ),
        wireless(
            "02:00:00:00:20:03",
            "laptop",
            "10.0.0.103",
            NET_LAN,
            AP_OFFICE,
            "demo-wifi",
            "ax",
            dev_id=DEV_ID["laptop"],
        ),
        wireless(
            "02:00:00:00:20:04", "tablet", "10.0.0.104", NET_LAN, AP_LIVING, "demo-wifi", "ac"
        ),
        wireless(
            "02:00:00:00:21:01",
            "living-room-tv",
            "10.0.0.105",
            NET_LAN,
            AP_LIVING,
            "demo-wifi",
            dev_id=DEV_ID["tv"],
        ),
        wireless(
            "02:00:00:00:30:01",
            "thermostat",
            "10.0.30.11",
            NET_IOT,
            AP_LIVING,
            "demo-iot",
            dev_id=DEV_ID["thermostat"],
        ),
        wireless("02:00:00:00:30:02", "doorbell", "10.0.30.12", NET_IOT, AP_GARAGE, "demo-iot"),
        wireless(
            "02:00:00:00:30:03",
            None,
            "10.0.30.13",
            NET_IOT,
            AP_LIVING,
            "demo-iot",
            oui="Espressif Inc.",
        ),
        wireless(
            "02:00:00:00:30:04",
            "smart-speaker",
            "10.0.30.14",
            NET_IOT,
            AP_BEDROOM,
            "demo-iot",
            dev_id=DEV_ID["speaker"],
        ),
        wireless(
            "02:00:00:00:30:05",
            None,
            "10.0.30.15",
            NET_IOT,
            AP_BEDROOM,
            "demo-iot",
            oui="Tuya Smart Inc.",
        ),
        # The only guest, and flagged as one. `is_guest` is a separate fact from
        # sitting on the guest VLAN, and it is what picks the guest icon, so a
        # demo without it never exercises two of the nine drawn icons.
        wireless(
            "02:00:00:00:40:01",
            "guest-phone",
            "10.0.100.20",
            NET_GUEST,
            AP_LIVING,
            "demo-guest",
            guest=True,
        ),
    ]

    networks = [
        {"_id": NET_LAN, "name": "lan", "vlan": 1, "ip_subnet": "10.0.0.1/24"},
        {"_id": NET_SERVERS, "name": "servers", "vlan": 20, "ip_subnet": "10.0.20.1/24"},
        {"_id": NET_IOT, "name": "iot", "vlan": 30, "ip_subnet": "10.0.30.1/24"},
        {"_id": NET_GUEST, "name": "guest", "vlan": 100, "ip_subnet": "10.0.100.1/24"},
    ]

    # The WAN subsystem is where isp_name lives, so the Internet node can be
    # labelled with the upstream provider rather than a generic string.
    health = [
        {
            "subsystem": "wan",
            "status": "ok",
            "isp_name": "Example ISP",
            "isp_organization": "Example ISP, Inc.",
            "wan_ip": "203.0.113.10",
        },
        {"subsystem": "wlan", "status": "ok"},
    ]

    # The controller's own graph. build-runner sits behind the hypervisor, which
    # stat/sta cannot express because the hypervisor is not a UniFi device. The
    # reverse proxy is deliberately left out, so the demo also shows what happens
    # when nothing knows where a client is.
    topology = {
        "vertices": [],
        "edges": [
            {
                "downlinkMac": "02:00:00:00:10:03",
                "uplinkMac": "02:00:00:00:10:02",
                "type": "WIRED",
            }
        ],
        "has_unknown_switch": False,
    }

    meta = {"rc": "ok"}
    return {
        "device": {"meta": meta, "data": devices},
        "client_active": {"meta": meta, "data": clients},
        "networkconf": {"meta": meta, "data": networks},
        "health": {"meta": meta, "data": health},
        "topology": topology,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payloads = build()
    for name, payload in payloads.items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # The topology payload is a graph rather than a record list.
        count = len(payload["data"]) if "data" in payload else len(payload.get("edges", []))
        unit = "records" if "data" in payload else "edges"
        print(f"wrote {path} ({count} {unit})")


if __name__ == "__main__":
    main()
