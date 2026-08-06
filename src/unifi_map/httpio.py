"""HTTP reads that are bounded, shared by the controller fetch and the CDN.

`assets.py` grew the first capped read and `client.py` needed the same guard,
which is the shape of a copy waiting to happen: two implementations of "read a
response body, stop at a limit" that drift apart in one of the details that
matters. `client.py` reads the controller, which is the endpoint people are
told it is ordinary to reach with `UNIFI_VERIFY_TLS=false`, so the two paths
must agree on how a hostile response is refused.

Two things live here:

- **`read_capped`**, the streaming read that stops at a cap instead of
  buffering an endless body whole. It existed first as `assets._read_capped`;
  this module is where the second copy would have landed, so it is where the
  one copy lives.
- **`Fetched`**, the minimal response object carrying only what callers use.
  `assets` originally handed back a hand-patched `requests.Response`; this is
  that same idea without the dependency on two private attributes of somebody
  else's library.

Keep the cap values with their callers. `MAX_ASSET_BYTES` says what an icon is
and `MAX_RESPONSE_BYTES` what a controller payload is; neither is a property of
reading.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class Fetched:
    """The parts of a response callers here actually use.

    `_fetch` used to hand back a `requests.Response` with `_content` and
    `_content_consumed` assigned by hand, because the body is streamed and read
    through a cap rather than by `requests` itself. That worked, and depended on
    two private attributes of somebody else's library staying where they are.

    Callers only ever touch `status_code`, `content` and `raise_for_status`, so
    those are all this carries.
    """

    status_code: int
    content: bytes
    url: str

    def raise_for_status(self) -> None:
        """Match `requests` closely enough that existing handlers still catch it."""
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for {self.url}")


def declared_size(response: requests.Response) -> int | None:
    """The declared `Content-Length`, if it is present and numeric.

    `None` covers both a missing header and a non-numeric one, so callers can
    use it as "no claim made" and rely on the streaming cap for the truth.
    """
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit():
        return int(declared)
    return None


def read_capped(response: requests.Response, limit: int) -> bytes | None:
    """Body bytes, or None once *limit* is passed.

    Reads in chunks and stops at the cap rather than measuring afterwards, so an
    oversized or endless response is abandoned instead of buffered whole. The
    response is closed on the way out either way, because a partially consumed
    streamed response cannot be relied on to release its connection.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                response.close()
                return None
            chunks.append(chunk)
    except requests.RequestException:
        response.close()
        return None
    response.close()
    return b"".join(chunks)
