"""Builds a tiny valid support-file archive as a fuzzing seed.

A pure-random mutation engine starting from nothing would spend nearly all of
its budget failing the gzip magic-byte check and never reach the tar-member or
JSON-parsing logic underneath. One small, valid, structurally-plausible
archive is enough to get the fuzzer past that gate so it can start mutating
toward interesting cases instead of away from them.

Deliberately minimal rather than a copy of tests/test_support.py's richer
fixture: a seed only needs to be valid enough to reach the code paths worth
fuzzing, and a smaller seed mutates and executes faster. Content follows this
project's own rule for non-identifying fixtures (see CONTRIBUTING.md):
locally-administered MAC, no real hostnames or subnets.

Standalone rather than importing from tests/, which is not part of the
installed package and is a fragile thing for build-time fuzzing
infrastructure to depend on.
"""

import io
import json
import sys
import tarfile
import zipfile
from pathlib import Path

_ROOT = "support-fuzz-seed"

_DEVICES = [
    {"default": [{"mac": "02:00:00:00:00:01", "sysid": "1", "model": "USW", "network_table": []}]}
]
_TOPOLOGY = {"default": {"data": [{"vertexType": "DEVICE", "mac": "02:00:00:00:00:01"}]}}
_INFRASTRUCTURE = {"default": {}}

_MEMBERS = {
    "unifi/devices.json": json.dumps(_DEVICES).encode(),
    "unifi/topology.json": json.dumps(_TOPOLOGY).encode(),
    "unifi/infrastructure.json": json.dumps(_INFRASTRUCTURE).encode(),
    "system/run/dnsmasq.lease": b"",
    "system/network/ip-neigh": b"",
}


def _build_archive() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in _MEMBERS.items():
            info = tarfile.TarInfo(f"{_ROOT}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def main() -> None:
    out_zip = Path(sys.argv[1])
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("support-seed.tgz", _build_archive())


if __name__ == "__main__":
    main()
