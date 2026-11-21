"""
Download a battle's server replay: parts 0000.wrpl, 0001.wrpl, … from Gaijin's replay host
(302 to its CDN, no login) until 404/403. One request at a time; each part retried with backoff,
since the CDN resets connections now and then. Parts already downloaded are kept, so it resumes.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

REPLAY_HOST = "https://wt-game-replays.warthunder.com"
PART_TRIES = 6
MAX_PARTS = 200
_HEADERS = {"user-agent": "wt-analytics (personal replay archive)"}


class NotAvailableYet(Exception):
    """Part 0 is not on the server (yet): try again later."""


def fetch_server_replay(session: str, into: Path, client: httpx.Client | None = None) -> list[Path]:
    """All parts of `session` into `into/NNNN.wrpl`; returns them in order."""
    into.mkdir(parents=True, exist_ok=True)
    http = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, read=300), headers=_HEADERS)
    try:
        parts = []
        for n in range(MAX_PARTS):
            path = into / f"{n:04d}.wrpl"
            if not path.exists() and not _download(http, f"{REPLAY_HOST}/{session}/{n:04d}.wrpl", path):
                break
            parts.append(path)
    finally:
        if client is None:
            http.close()
    if not parts:
        raise NotAvailableYet(session)
    return parts


def _download(http: httpx.Client, url: str, path: Path) -> bool:
    """True when stored, False when the server says the part does not exist."""
    error: Exception | None = None
    for attempt in range(PART_TRIES):
        try:
            with http.stream("GET", url) as response:
                if response.status_code in (403, 404):
                    return False
                response.raise_for_status()
                tmp = path.with_suffix(".part")
                with tmp.open("wb") as f:
                    for chunk in response.iter_bytes(1 << 20):
                        f.write(chunk)
                expected = response.headers.get("content-length")
                if expected is not None and tmp.stat().st_size != int(expected):
                    raise httpx.ReadError(f"short read on {url}")
                tmp.replace(path)
                return True
        except httpx.HTTPError as e:
            error = e
            time.sleep(2 * 2**attempt)
    raise error  # type: ignore[misc]
