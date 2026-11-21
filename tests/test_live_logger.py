"""The live logger against a fake game: battle start/end detection, incremental hudmsg, readable logs."""

import http.server
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import zstandard

from wt_analytics.helper import live_logger


def fake_game(battle: dict, hud_requests: list) -> http.server.ThreadingHTTPServer:
    class Game(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive, like a real server
        wbufsize = 1 << 16

        def do_GET(self):
            running = battle["from"] <= time.time() < battle["to"]
            url = urlsplit(self.path)
            if url.path == "/hudmsg":
                hud_requests.append(int(parse_qs(url.query)["lastEvt"][0]))
                body = {"events": [{"id": len(hud_requests), "msg": "x"}], "damage": []}
            elif url.path == "/":
                body = '<script src="app.js"></script>'
            elif url.path == "/app.js":
                body = 'fetch("/new_thing.json?x"); x = "/a"'
            elif url.path == "/a":
                body = "<html>not an endpoint</html>"
            elif url.path == "/map_info.json":
                body = {"valid": running}
            else:  # like the real game: /state and /indicators are valid in the hangar too
                body = {"valid": True, "path": url.path}
            data = (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Game)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_records_one_battle_from_start_to_end(tmp_path, monkeypatch):
    battle = {"from": time.time() + 0.5, "to": time.time() + 2.5}
    hud_requests = []
    server = fake_game(battle, hud_requests)
    monkeypatch.setattr(live_logger, "PORT", server.server_address[1])
    monkeypatch.setattr(live_logger, "END_AFTER_S", 1.0)
    monkeypatch.setattr(live_logger, "IDLE_PROBE_S", 0.1)

    cut_off = tmp_path / "20261121T215038Z"  # an earlier recording the helper was stopped during
    cut_off.mkdir()
    (cut_off / "state.jsonl.zst").write_bytes(b"")
    logger = live_logger.LiveLogger(tmp_path)
    thread = logger.start()
    deadline = time.time() + 10
    while len(list(tmp_path.glob("*/meta.json"))) < 2 and time.time() < deadline:
        time.sleep(0.1)
    logger.stop()
    thread.join(5)
    server.shutdown()

    [(old, old_meta), (folder, meta)] = live_logger.completed_battles(tmp_path)
    assert old == cut_off and old_meta["cut_off"] and old_meta["started"] == 1795297838 and old_meta["endpoints"] == ["/state"]
    assert not logger.in_battle.is_set()
    assert battle["from"] <= meta["started"] <= battle["from"] + 0.3
    assert battle["to"] - 1.1 <= meta["ended"] <= battle["to"]  # the signal is read once a second
    assert "/new_thing.json" in meta["endpoints"] and "/a" not in meta["endpoints"]  # found in the script; JSON only
    assert hud_requests == list(range(len(hud_requests))) and len(hud_requests) >= 3  # incremental ids
    with (folder / "state.jsonl.zst").open("rb") as f:
        records = [json.loads(line) for line in zstandard.ZstdDecompressor().stream_reader(f).read().splitlines()]
    assert 15 <= len(records) <= 30 and all(r["status"] == 200 for r in records)  # ~10 Hz for ~2 s
