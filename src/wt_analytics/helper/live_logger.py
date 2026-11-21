"""
Records the game's local API (http://127.0.0.1:8111) during battles. Records only: nothing is
shown or sent anywhere while a battle runs (rule 1). Each battle becomes a folder
`staging/live/<UTC start>/` with one zstd JSONL file per endpoint; every line is
{"t": unix time, "path", "status", "body": the raw response text} — never parsed away, so fields
we don't understand yet are kept. `discovery.json` holds the page and its scripts; `meta.json`
is written when the battle ends.

A battle is running while `/indicators` says `"valid": true`; it has ended after `END_AFTER_S`
seconds without that (or without the game answering).

CPU budget (< 1 % of a core while playing): one thread, one keep-alive connection and a
minimal HTTP client — about 0.2 ms of CPU per request, ~30 requests/s at the default rates.
"""

from __future__ import annotations

import base64
import heapq
import json
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import zstandard

log = logging.getLogger(__name__)

HOST, PORT = "127.0.0.1", 8111
BASE = f"http://{HOST}:{PORT}"
TIMEOUT_S = 1.0
END_AFTER_S = 5.0
IDLE_PROBE_S = 1.0
FLUSH_EVERY_S = 5.0
BATTLE_SIGNAL = "/indicators"

#: Polling rates in Hz (configurable). hudmsg/gamechat are polled incrementally; map_info and
#: map.img are kept once per battle and whenever map_info changes.
DEFAULT_RATES: dict[str, float] = {
    "/state": 10,
    "/indicators": 10,
    "/map_obj.json": 5,
    "/hudmsg": 2,
    "/gamechat": 2,
    "/mission.json": 1,
    "/map_info.json": 0.2,
}
_JS_ENDPOINT = re.compile(r"""["'](/[a-z_]+(?:\.json)?)[?"']""")
_NOT_POLLED = {"/", "/hudmsg", "/gamechat", "/map.img"}


class _Http:
    """GET over one persistent connection; reconnects on any error. Content-Length, chunked or close-delimited."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._file = None

    def get(self, path: str) -> tuple[int, bytes, dict[bytes, bytes]]:
        try:
            return self._get(path)
        except OSError:  # a kept-alive connection may have been closed by the game: once more, fresh
            self.close()
        try:
            return self._get(path)
        except OSError:
            self.close()
            raise

    def _get(self, path: str) -> tuple[int, bytes, dict[bytes, bytes]]:
        if self._sock is None:
            self._sock = socket.create_connection((HOST, PORT), timeout=TIMEOUT_S)
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._file = self._sock.makefile("rb")
        self._sock.sendall(f"GET {path} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n\r\n".encode())
        status_line = self._file.readline()
        if not status_line:
            raise ConnectionError("closed")
        status = int(status_line.split()[1])
        headers = {}
        while (line := self._file.readline()) not in (b"\r\n", b"\n", b""):
            key, _, value = line.partition(b":")
            headers[key.strip().lower()] = value.strip()
        if b"content-length" in headers:
            body = self._read(int(headers[b"content-length"]))
        elif headers.get(b"transfer-encoding", b"").lower() == b"chunked":
            body = self._chunked()
        else:
            body = self._file.read()
            self.close()
        if headers.get(b"connection", b"").lower() == b"close":
            self.close()
        return status, body, headers

    def _read(self, n: int) -> bytes:
        data = self._file.read(n)
        if len(data) != n:
            raise ConnectionError("short body")
        return data

    def _chunked(self) -> bytes:
        parts = []
        while size := int(self._file.readline().split(b";")[0], 16):
            parts.append(self._read(size))
            self._file.readline()
        while self._file.readline() not in (b"\r\n", b"\n", b""):
            pass
        return b"".join(parts)

    def get_text(self, path: str) -> str | None:
        try:
            status, body, _ = self.get(path)
        except (OSError, ValueError):
            return None
        return body.decode("utf-8", "replace") if status == 200 else None

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
        self._sock = self._file = None


class _Writer:
    """One endpoint's zstd JSONL stream, flushed as a zstd block every few seconds (crash-safe up to then)."""

    def __init__(self, path: Path) -> None:
        self._file = path.open("ab")
        self._stream = zstandard.ZstdCompressor(level=3).stream_writer(self._file, closefd=False)
        self._flushed = time.monotonic()

    def write(self, record: dict) -> None:
        self._stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
        if time.monotonic() - self._flushed > FLUSH_EVERY_S:
            self._stream.flush(zstandard.FLUSH_BLOCK)
            self._flushed = time.monotonic()

    def close(self) -> None:
        self._stream.flush(zstandard.FLUSH_FRAME)
        self._stream.close()
        self._file.close()


@dataclass
class _Battle:
    folder: Path
    started: float
    last_valid: float
    writers: dict[str, _Writer] = field(default_factory=dict)
    last_evt: int = 0
    last_dmg: int = 0
    last_chat: int = 0
    map_info: str | None = None
    map_images: int = 0

    def writer(self, endpoint: str) -> _Writer:
        if endpoint not in self.writers:
            name = endpoint.strip("/").removesuffix(".json").replace("/", "_")
            self.writers[endpoint] = _Writer(self.folder / f"{name}.jsonl.zst")
        return self.writers[endpoint]


class LiveLogger:
    """Run with `start()` (its own thread). `in_battle` is set while a battle is being recorded."""

    def __init__(self, live_root: Path, rates: dict[str, float] | None = None) -> None:
        self.root = live_root
        self.rates = {**DEFAULT_RATES, **(rates or {})}
        self.in_battle = threading.Event()
        self._stop = threading.Event()
        self._http = _Http()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._main, name="live-logger", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def _main(self) -> None:
        while not self._stop.is_set():
            battle = None
            try:
                if _is_valid(self._http.get_text(BATTLE_SIGNAL)):
                    battle = self._begin()
                    self._record(battle)
                else:
                    self._stop.wait(IDLE_PROBE_S)
            except Exception:  # never die: log and keep watching
                log.exception("live logger error")
                self._stop.wait(5)
            finally:
                if battle:
                    self._end(battle)
        self._http.close()

    def _begin(self) -> _Battle:
        now = time.time()
        folder = self.root / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
        folder.mkdir(parents=True, exist_ok=True)
        self.in_battle.set()
        log.info("battle started, recording to %s", folder)
        battle = _Battle(folder, now, last_valid=now)
        self._discover(battle)
        return battle

    def _discover(self, battle: _Battle) -> None:
        """Keep the page and its scripts, and also poll any endpoints they mention that we don't know."""
        page = self._http.get_text("/")
        found = {"/": page} if page is not None else {}
        for src in re.findall(r'src="([^"]+\.js)"', page or ""):
            path = src if src.startswith("/") else f"/{src}"
            if (js := self._http.get_text(path)) is not None:
                found[path] = js
        (battle.folder / "discovery.json").write_text(json.dumps(found), encoding="utf-8")
        for endpoint in sorted({m for text in found.values() for m in _JS_ENDPOINT.findall(text)}):
            if endpoint not in self.rates and endpoint not in _NOT_POLLED:
                self.rates[endpoint] = 1  # unknown endpoint: record it slowly rather than miss it
                log.info("discovered endpoint %s", endpoint)

    def _record(self, battle: _Battle) -> None:
        now = time.monotonic()
        due = [(now, endpoint) for endpoint in self.rates]
        heapq.heapify(due)
        while not self._stop.is_set() and time.time() - battle.last_valid < END_AFTER_S:
            when, endpoint = heapq.heappop(due)
            if (wait := when - time.monotonic()) > 0:
                self._stop.wait(wait)
            self._poll(battle, endpoint)
            heapq.heappush(due, (max(when + 1 / self.rates[endpoint], time.monotonic()), endpoint))

    def _poll(self, battle: _Battle, endpoint: str) -> None:
        path = self._path(battle, endpoint)
        t = time.time()
        try:
            status, raw, _ = self._http.get(path)
        except (OSError, ValueError) as e:
            battle.writer(endpoint).write({"t": t, "path": path, "status": 0, "error": type(e).__name__})
            return
        body = raw.decode("utf-8", "replace")
        battle.writer(endpoint).write({"t": t, "path": path, "status": status, "body": body})
        if status == 200:
            self._after(battle, endpoint, body)

    @staticmethod
    def _path(battle: _Battle, endpoint: str) -> str:
        if endpoint == "/hudmsg":
            return f"/hudmsg?lastEvt={battle.last_evt}&lastDmg={battle.last_dmg}"
        if endpoint == "/gamechat":
            return f"/gamechat?lastId={battle.last_chat}"
        return endpoint

    def _after(self, battle: _Battle, endpoint: str, body: str) -> None:
        if endpoint == BATTLE_SIGNAL:
            if _is_valid(body):
                battle.last_valid = time.time()
        elif endpoint == "/map_info.json":
            if body != battle.map_info and _is_valid(body):  # first time, and whenever the map changes
                battle.map_info = body
                self._save_map_image(battle)
        elif endpoint == "/hudmsg":
            data = _json(body)
            if isinstance(data, dict):
                battle.last_evt = _max_id(battle.last_evt, data.get("events"))
                battle.last_dmg = _max_id(battle.last_dmg, data.get("damage"))
        elif endpoint == "/gamechat":
            battle.last_chat = _max_id(battle.last_chat, _json(body))

    def _save_map_image(self, battle: _Battle) -> None:
        try:
            status, raw, headers = self._http.get("/map.img")
        except (OSError, ValueError):
            return
        content_type = headers.get(b"content-type", b"").decode()
        battle.writer("/map.img").write({"t": time.time(), "status": status, "content_type": content_type, "body_b64": base64.b64encode(raw).decode()})
        battle.map_images += 1

    def _end(self, battle: _Battle) -> None:
        for writer in battle.writers.values():
            writer.close()
        meta = {"started": battle.started, "ended": battle.last_valid, "endpoints": sorted(battle.writers), "map_images": battle.map_images}
        (battle.folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self.in_battle.clear()
        log.info("battle ended (%d s recorded)", battle.last_valid - battle.started)


def _json(body: str | None):
    try:
        return json.loads(body) if body is not None else None
    except ValueError:
        return None


def _is_valid(body: str | None) -> bool:
    data = _json(body)
    return isinstance(data, dict) and bool(data.get("valid"))


def _max_id(current: int, items) -> int:
    if not isinstance(items, list):
        return current
    ids = [int(i["id"]) for i in items if isinstance(i, dict) and str(i.get("id", "")).isdigit()]
    return max([current, *ids])


def completed_battles(live_root: Path) -> list[tuple[Path, dict]]:
    """Recorded battles that have ended (have meta.json), oldest first."""
    return [(m.parent, json.loads(m.read_text(encoding="utf-8"))) for m in sorted(live_root.glob("*/meta.json"))]
