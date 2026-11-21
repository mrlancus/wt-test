"""
The pipeline container's HTTP service. The Worker drives one job per battle:

    PUT    /jobs/<job>/in/<source>/<name>   upload an input file (source: client | server)
    POST   /jobs/<job>/run                  decode every source, body {"me_user_id": "..."}
    GET    /jobs/<job>/out/<source>/<name>  fetch an output file
    DELETE /jobs/<job>                      drop the job's files
    GET    /health                          versions

Sources decode in parallel processes, so a battle takes about as long as its server replay.
"""

from __future__ import annotations

import json
import re
import shutil
import traceback
from concurrent.futures import ProcessPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from wt_analytics.common.schema import DECODER, DECODER_VERSION, SCHEMA_VERSION
from wt_analytics.pipeline.decode import decode
from wt_analytics.pipeline.summary import match_summary

WORK = Path("/tmp/jobs")
SOURCES = ("client", "server")
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_CHUNK = 1 << 20


def run_job(job: Path, me_user_id: str) -> dict[str, Any]:
    """Decode each source of a job; summary taken from the server replay when there is one."""
    present = [s for s in SOURCES if any((job / "in" / s).glob("*.wrpl"))]
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=max(1, len(present))) as pool:
        futures = {s: pool.submit(_decode_source, job, s) for s in present}
        for source, future in futures.items():
            try:
                results[source] = future.result()
            except Exception as e:  # one bad source must not lose the other
                errors[source] = f"{type(e).__name__}: {e}"
    # The server replay covers the whole battle; the client replay fills what it lacks (e.g. country).
    summaries = [
        match_summary(json.loads((job / "out" / s / "match.json").read_text(encoding="utf-8")), me_user_id)
        for s in ("server", "client")
        if s in results
    ]
    summary = None
    if summaries:
        summary = {k: next((s[k] for s in summaries if s[k] not in (None, [])), summaries[0][k]) for k in summaries[0]}
    return {
        "decoder": f"{DECODER}-{DECODER_VERSION}",
        "schema_version": SCHEMA_VERSION,
        "sources": results,
        "errors": errors,
        "summary": summary,
    }


def _decode_source(job: Path, source: str) -> dict[str, Any]:
    inputs = sorted((job / "in" / source).glob("*.wrpl"))
    out = job / "out" / source
    decoded = decode(inputs, out)
    return {"match": decoded.match_name, "files": [p.name for p in decoded.files]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            return self._json({"ok": True, "decoder": f"{DECODER}-{DECODER_VERSION}", "schema_version": SCHEMA_VERSION})
        parts = self._parts("jobs", None, "out", None, None)
        if not parts:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        path = WORK / parts[1] / "out" / parts[3] / parts[4]
        if not path.is_file():
            return self._json({"error": "no such output"}, HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        with path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile, _CHUNK)

    def do_PUT(self) -> None:
        parts = self._parts("jobs", None, "in", None, None)
        if not parts or parts[3] not in SOURCES:
            return self._json({"error": "bad input path"}, HTTPStatus.BAD_REQUEST)
        dst = WORK / parts[1] / "in" / parts[3] / parts[4]
        dst.parent.mkdir(parents=True, exist_ok=True)
        remaining = int(self.headers.get("Content-Length", "0"))
        tmp = dst.with_suffix(dst.suffix + ".part")
        with tmp.open("wb") as f:
            while remaining:
                chunk = self.rfile.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if remaining:
            tmp.unlink(missing_ok=True)
            return self._json({"error": "truncated upload"}, HTTPStatus.BAD_REQUEST)
        tmp.replace(dst)
        self._json({"ok": True, "bytes": dst.stat().st_size})

    def do_POST(self) -> None:
        parts = self._parts("jobs", None, "run")
        if not parts:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        try:
            self._json(run_job(WORK / parts[1], str(body["me_user_id"])))
        except Exception:
            self._json({"error": traceback.format_exc(limit=5)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parts = self._parts("jobs", None)
        if not parts:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        shutil.rmtree(WORK / parts[1], ignore_errors=True)
        self._json({"ok": True})

    def _parts(self, *pattern: str | None) -> list[str] | None:
        """Path segments if they match `pattern` (None = any safe segment), else None."""
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if len(parts) != len(pattern):
            return None
        for seg, want in zip(parts, pattern):
            if not _SAFE.match(seg) or (want is not None and seg != want):
                return None
        return parts

    def _json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
