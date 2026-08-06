"""The controller client: response classification, capped reads, generations.

No test here touches the network. The session is a fake with scripted
responses, and snapshot writes go to a temp directory. The one behaviour the
redirect tests live for, `_Session.rebuild_auth` stripping `X-API-KEY` across a
host change, is already covered in `test_render.py` and is not repeated here.
"""

from __future__ import annotations

import os
import stat

import pytest
import requests

from unifi_map.client import Snapshot, UniFiClient, UniFiError, unwrap
from unifi_map.config import ExporterConfig


def _client(session: _ScriptedSession | None = None) -> UniFiClient:
    client = UniFiClient(ExporterConfig("console.example.com", "secret"))
    if session is not None:
        client.session = session
    return client


class _Streamed:
    """A response shaped like the streaming ones the client now requests.

    Every controller response is streamed through a size cap, so the double has
    to stream too: a `.content`-only double would assert against an interface
    the code no longer uses, which is the failure mode this module was written
    to prevent in the first place.
    """

    def __init__(self, body: bytes = b"", status: int = 200, headers: dict | None = None):
        self._body = body
        self.status_code = status
        self.headers = headers or {}
        self.closed = False
        self.chunks_served = 0

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self._body), chunk_size):
            self.chunks_served += 1
            yield self._body[start : start + chunk_size]

    def close(self):
        self.closed = True


class _ScriptedSession:
    """A session that answers each URL from a script, or raises for it.

    A `requests.RequestException` instance in the script models a transport
    failure; anything else is a `_Streamed` response.
    """

    def __init__(self, responses: dict[str, object] | None = None):
        self.responses = responses or {}
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        answer = self.responses.get(url)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class TestUnwrap:
    def test_the_v1_envelope_is_absorbed(self):
        assert unwrap({"meta": {"rc": "ok"}, "data": [{"a": 1}]}) == [{"a": 1}]

    def test_a_bare_v2_list_is_absorbed(self):
        assert unwrap([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    @pytest.mark.parametrize(
        "payload",
        [None, "text", 42, {}, {"data": "not a list"}, [1, "x", None]],
    )
    def test_anything_unexpected_thins_to_nothing(self, payload):
        # A controller upgrade must thin the diagram, never raise.
        assert unwrap(payload) == []

    def test_non_dict_records_are_dropped(self):
        assert unwrap({"data": [{"a": 1}, "junk", None]}) == [{"a": 1}]


class TestFetch:
    URL = "https://console.example.com/proxy/network/api/s/default/stat/device"

    @staticmethod
    def _path() -> str:
        return "api/s/{site}/stat/device"

    def _respond(self, body=b'{"data": [1]}', status=200, headers=None):
        return _client(_ScriptedSession({self.URL: _Streamed(body, status, headers)}))

    def test_a_json_payload_is_returned(self):
        client = self._respond(b'{"data": [1]}')
        assert client._fetch(self._path()) == {"data": [1]}

    @pytest.mark.parametrize("status", [401, 403])
    def test_an_auth_failure_names_the_api_key(self, status):
        # The two statuses a wrong or revoked key produces; the message must say
        # what to check rather than just report the number.
        with pytest.raises(UniFiError, match="API key"):
            self._respond(status=status)._fetch(self._path())

    def test_other_statuses_name_the_code_and_url(self):
        with pytest.raises(UniFiError, match="HTTP 500"):
            self._respond(status=500)._fetch(self._path())

    def test_a_non_json_body_names_the_url(self):
        with pytest.raises(UniFiError, match="Non-JSON"):
            self._respond(b"<html>not json</html>")._fetch(self._path())

    def test_a_transport_failure_names_the_remedy(self):
        client = _client(
            _ScriptedSession({self.URL: requests.ConnectionError("Connection refused")})
        )
        with pytest.raises(UniFiError, match="Check UNIFI_HOST"):
            client._fetch(self._path())


class TestResponseCaps:
    """The controller is read through the same ceiling the CDN is (KAN-134)."""

    URL = "https://console.example.com/proxy/network/api/s/default/stat/device"

    @staticmethod
    def _path() -> str:
        return "api/s/{site}/stat/device"

    def test_a_huge_declared_length_is_refused_before_the_body_is_read(self):
        from unifi_map.client import MAX_RESPONSE_BYTES

        response = _Streamed(b"x" * 16, headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)})
        client = _client(_ScriptedSession({self.URL: response}))
        with pytest.raises(UniFiError, match="claims"):
            client._fetch(self._path())
        # Refused on the declared length, so the stream is never started.
        assert response.chunks_served == 0

    def test_a_lying_content_length_is_still_caught_while_streaming(self):
        from unifi_map.client import MAX_RESPONSE_BYTES

        response = _Streamed(b"x" * (MAX_RESPONSE_BYTES + 1), headers={"Content-Length": "10"})
        client = _client(_ScriptedSession({self.URL: response}))
        with pytest.raises(UniFiError, match="exceeded"):
            client._fetch(self._path())
        assert response.closed
        # The cap stops the read rather than measuring after the fact, so a
        # body twice the limit is never buffered whole.
        served = response.chunks_served * 64 * 1024
        assert served <= MAX_RESPONSE_BYTES + 64 * 1024

    def test_the_raw_path_is_capped_too(self):
        from unifi_map.client import MAX_RESPONSE_BYTES

        url = "https://console.example.com/proxy/network/manage/"
        response = _Streamed(b"x" * (MAX_RESPONSE_BYTES + 1))
        client = _client(_ScriptedSession({url: response}))
        with pytest.raises(UniFiError, match="exceeded"):
            client._fetch_raw("manage/")

    def test_the_protect_endpoint_reads_json_from_the_console_root(self):
        url = "https://console.example.com/proxy/protect/integration/v1/cameras"
        client = _client(_ScriptedSession({url: _Streamed(b'[{"mac": "1"}]')}))
        assert client._fetch_json("proxy/protect/integration/v1/cameras") == [{"mac": "1"}]


class TestSnapshotFetch:
    """`snapshot()` gathers every endpoint; only the required ones may fail."""

    BASE = "https://console.example.com"

    @staticmethod
    def _url(path: str, proxy: bool) -> str:
        return (
            f"{TestSnapshotFetch.BASE}/proxy/network/{path}"
            if proxy
            else f"{TestSnapshotFetch.BASE}/{path}"
        )

    def _all_endpoints(self) -> dict[str, object]:
        from unifi_map.client import ENDPOINTS, EXTRA_ENDPOINTS

        responses: dict[str, object] = {}
        for path in ENDPOINTS.values():
            responses[self._url(path.format(site="default"), proxy=True)] = _Streamed(
                b'{"data": []}'
            )
        for path in EXTRA_ENDPOINTS.values():
            responses[self._url(path, proxy=False)] = _Streamed(b"[]")
        return responses

    def test_a_full_fetch_has_every_endpoint(self):
        client = _client(_ScriptedSession(self._all_endpoints()))
        snapshot = client.snapshot()
        assert set(snapshot.payloads) == {
            "device",
            "client_active",
            "networkconf",
            "health",
            "fingerprint",
            "topology",
            "protect_cameras",
        }

    def test_a_failed_required_endpoint_aborts(self):
        responses = self._all_endpoints()
        device_url = self._url("api/s/default/stat/device", proxy=True)
        responses[device_url] = requests.ConnectionError("boom")
        with pytest.raises(UniFiError):
            _client(_ScriptedSession(responses)).snapshot()

    def test_a_failed_optional_endpoint_warns_and_continues(self, caplog):
        responses = self._all_endpoints()
        topology_url = self._url("v2/api/site/default/topology", proxy=True)
        responses[topology_url] = requests.ConnectionError("boom")
        client = _client(_ScriptedSession(responses))
        with caplog.at_level("WARNING"):
            snapshot = client.snapshot()
        assert snapshot.get("topology") is None
        assert snapshot.get("device") == {"data": []}
        assert any("topology" in r.getMessage() for r in caplog.records)

    def test_missing_protect_is_ordinary_and_debug_only(self, caplog):
        # Absent whenever the app is not installed, which is normal, so it must
        # not rise above the debug level.
        responses = self._all_endpoints()
        protect_url = self._url("proxy/protect/integration/v1/cameras", proxy=False)
        responses[protect_url] = requests.ConnectionError("boom")
        client = _client(_ScriptedSession(responses))
        with caplog.at_level("DEBUG"):
            snapshot = client.snapshot()
        assert "protect_cameras" not in snapshot.payloads
        assert not any(
            r.levelno >= 30 and "protect" in r.getMessage().lower() for r in caplog.records
        )


class TestSnapshotGenerations:
    """A snapshot is a generation switched into place, so a reader never sees a mix.

    Each fetch writes a complete set under `gens/` and then swaps a pointer to
    it. The properties that matter: an interrupted fetch leaves the previous
    generation readable, a reader only ever sees one complete set, and a
    pre-generation flat cache keeps working and is migrated by the next fetch.
    """

    def test_write_then_read_round_trips(self, tmp_path):
        Snapshot(payloads={"device": {"data": [1]}}).write(tmp_path)
        assert Snapshot.read(tmp_path).get("device") == {"data": [1]}

    def test_a_legacy_flat_cache_still_reads(self, tmp_path):
        # The shipped demo dataset, and anything written before generations.
        (tmp_path / "device.json").write_text('{"data": [1]}', encoding="utf-8")
        assert Snapshot.read(tmp_path).get("device") == {"data": [1]}

    def test_a_new_fetch_migrates_a_legacy_cache(self, tmp_path):
        (tmp_path / "device.json").write_text('{"data": [1]}', encoding="utf-8")
        Snapshot(payloads={"device": {"data": [2]}}).write(tmp_path)
        # The flat copy is superseded by the generation and removed; it is a
        # full inventory nothing reads any more.
        assert not (tmp_path / "device.json").exists()
        assert Snapshot.read(tmp_path).get("device") == {"data": [2]}

    def test_an_interrupted_fetch_leaves_the_previous_generation_readable(self, tmp_path):
        """The property that motivated generations: cut off before the pointer
        swap, the old snapshot is still what read() returns, because the pointer
        never moved."""
        from unifi_map.client import GENERATIONS_DIR

        Snapshot(payloads={"device": {"data": [1]}}).write(tmp_path)
        # A fetch that wrote files but died before the pointer swap.
        partial = tmp_path / GENERATIONS_DIR / "20260805T120000000000-1"
        partial.mkdir(parents=True)
        (partial / "device.json").write_text('{"data": [999]}', encoding="utf-8")
        assert Snapshot.read(tmp_path).get("device") == {"data": [1]}
        # The next complete fetch removes the debris.
        Snapshot(payloads={"device": {"data": [3]}}).write(tmp_path)
        assert not partial.exists()
        assert Snapshot.read(tmp_path).get("device") == {"data": [3]}

    def test_only_the_current_generation_is_kept(self, tmp_path):
        from unifi_map.client import GENERATIONS_DIR

        Snapshot(payloads={"device": {"data": [1]}}).write(tmp_path)
        Snapshot(payloads={"device": {"data": [2]}}).write(tmp_path)
        generations = list((tmp_path / GENERATIONS_DIR).iterdir())
        assert len(generations) == 1, "superseded generation left a second inventory"
        assert Snapshot.read(tmp_path).get("device") == {"data": [2]}

    def test_a_pointer_to_a_missing_generation_is_refused_loudly(self, tmp_path):
        from unifi_map.client import CURRENT_POINTER

        Snapshot(payloads={"device": {"data": [1]}}).write(tmp_path)
        (tmp_path / CURRENT_POINTER).write_text("gens/20260805T000000000000-99\n", encoding="utf-8")
        with pytest.raises(UniFiError, match="missing"):
            Snapshot.read(tmp_path)

    def test_a_pointer_that_is_not_a_generation_is_refused(self, tmp_path):
        from unifi_map.client import CURRENT_POINTER

        (tmp_path / CURRENT_POINTER).write_text("../../etc\n", encoding="utf-8")
        with pytest.raises(UniFiError, match="not a generation"):
            Snapshot.read(tmp_path)

    def test_a_cache_with_no_snapshot_at_all_names_the_problem(self, tmp_path):
        with pytest.raises(UniFiError, match="no snapshot files"):
            Snapshot.read(tmp_path)

    def test_a_cache_without_the_directory_is_refused(self, tmp_path):
        with pytest.raises(UniFiError, match="`unifi-map fetch`"):
            Snapshot.read(tmp_path / "absent")

    def test_corrupt_json_in_a_generation_names_the_file(self, tmp_path):
        from unifi_map.client import GENERATIONS_DIR

        Snapshot(payloads={"device": {"data": [1]}}).write(tmp_path)
        generation = next((tmp_path / GENERATIONS_DIR).iterdir())
        (generation / "device.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(UniFiError, match="not readable JSON"):
            Snapshot.read(tmp_path)

    def test_generation_files_are_private(self, tmp_path):
        if os.name != "posix":
            pytest.skip("POSIX modes only")
        Snapshot(payloads={"device": {"data": [1]}}).write(tmp_path)
        for path in (tmp_path / "gens").rglob("*.json"):
            assert not stat.S_IMODE(path.stat().st_mode) & 0o077, path
        assert not stat.S_IMODE((tmp_path / "gens").stat().st_mode) & 0o077
