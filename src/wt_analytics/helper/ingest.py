"""
The local queue: one folder per battle in the staging area, with its progress in `state.json`.

A battle goes: stage the client replay → copy it to the share → copy its live 8111 log (if
recorded) to the share → fetch the server replay →
copy it to the share → decode both → copy the decoded tables to the share → write its manifest →
send the summary to the website → clear staging. Each step is recorded when done, so a restart,
an offline share or a lost connection only delays it. Nothing is deleted locally until it is on
the share with a verified hash.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

import httpx

from wt_analytics.common.config import Config
from wt_analytics.helper.api import Api
from wt_analytics.helper.live_logger import completed_battles
from wt_analytics.helper.server_fetch import NotAvailableYet, fetch_server_replay
from wt_analytics.helper.share import Share, ShareOffline, sha256
from wt_analytics.pipeline.battle import DECODER_ID, Interrupted, decode_battle

# Waits before asking for a server replay again when it is not there yet (s); then decode without it.
SERVER_RETRY_DELAYS = (120, 600, 1800, 3600, 10800, 43200)
#: A server replay still missing this long after the battle started is gone (old battles): don't wait.
SERVER_GONE_AFTER_S = 86400
RETRY_DELAY = 300  # after a transient failure (share offline, network)
#: A live log belongs to a replay if it started within this many seconds of the replay's start time.
LIVE_MATCH_S = 600
UNMATCHED_LIVE_AFTER_S = 86400  # live logs with no replay (test drives, …) go to the share after a day
STEPS = ("raw_client", "raw_live", "server", "raw_server", "decode", "publish", "manifest", "summary")


@dataclass
class Job:
    session: str
    map: str
    started: str  # ISO UTC
    replay_version: int
    done: list[str] = field(default_factory=list)
    server: str = "pending"  # pending | done | missing
    server_attempts: int = 0
    live: str | None = None  # the live log folder taken for this battle, or None
    next_try: float = 0.0
    last_error: str | None = None
    hashes: dict[str, str] = field(default_factory=dict)  # share-relative path -> sha256
    result: dict[str, Any] | None = None


class Queue:
    def __init__(self, cfg: Config, api: Api | None = None) -> None:
        self.cfg = cfg
        self.share = Share(cfg.share)
        self.api = api or Api(cfg)
        self.live_root = cfg.staging / "live"
        self.live_root.mkdir(parents=True, exist_ok=True)
        self._should_pause: Callable[[], bool] = lambda: False

    # --- adding battles

    def add(self, replay: Path) -> Job:
        """Queue a client replay (copied into staging at once). Idempotent per session."""
        from heat3d_ext_warthunder import wrpl

        header = wrpl.read_header(replay.read_bytes())
        session = header["sessionId"]
        folder = self.cfg.staging / session
        if (folder / "state.json").exists():
            return self._load(folder)
        staged = folder / "client" / f"{session}.wrpl"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(replay, staged)
        if sha256(staged) != sha256(replay):
            raise OSError(f"staging copy of {replay} differs")
        started = datetime.fromtimestamp(header["startTime"], UTC).isoformat()
        job = Job(session, header["map"], started, header["version"])
        self._save(job)
        return job

    def pull_inbox(self) -> int:
        """Queue replays uploaded on the website, then remove them from the website's inbox."""
        added = 0
        for item in self.api.inbox():
            tmp = self.cfg.staging / f"inbox-{item['name']}"
            self.add(self.api.download_inbox(item["name"], tmp))
            tmp.unlink()
            self.api.delete_inbox(item["name"])
            added += 1
        return added

    # --- working through the queue

    def run_due(self, should_pause: Callable[[], bool] = lambda: False) -> list[Job]:
        """Advance every battle whose next try is due. `should_pause` stops between steps (a battle started)."""
        worked = []
        for state in sorted(self.cfg.staging.glob("*/state.json")):
            job = self._load(state.parent)
            if job.next_try > time.time():
                continue
            self.advance(job, should_pause)
            worked.append(job)
        return worked

    def advance(self, job: Job, should_pause: Callable[[], bool] = lambda: False) -> Job:
        self._should_pause = should_pause
        for step in STEPS:
            if step in job.done:
                continue
            if should_pause():
                return job
            try:
                if not getattr(self, f"_step_{step}")(job):
                    break  # waiting (server replay not there yet)
                job.done.append(step)
                job.last_error = None
            except Interrupted:
                break  # a battle started: carry on from this step when it is over
            except (ShareOffline, httpx.HTTPError, OSError) as e:
                job.last_error = f"{step}: {type(e).__name__}: {e}"
                job.next_try = time.time() + RETRY_DELAY
                break
            finally:
                self._save(job)
        if all(s in job.done for s in STEPS):
            shutil.rmtree(self.cfg.staging / job.session)
        return job

    # --- steps: True when done, False when waiting

    def _step_raw_client(self, job: Job) -> bool:
        rel = f"raw/replays/client/{job.started[:10]}/{job.session}.wrpl"
        job.hashes[rel] = self.share.put(self._dir(job) / "client" / f"{job.session}.wrpl", rel)
        return True

    def _step_raw_live(self, job: Job) -> bool:
        start = datetime.fromisoformat(job.started).timestamp()
        near = [(abs(meta["started"] - start), folder) for folder, meta in completed_battles(self.live_root)]
        near = [n for n in near if n[0] <= LIVE_MATCH_S]
        if near:
            folder = min(near)[1]
            rel = f"raw/live/{job.session}"
            job.hashes.update({f"{rel}/{k}": v for k, v in self.share.put_tree(folder, rel).items()})
            job.live = folder.name
            shutil.rmtree(folder)
        return True

    def sweep_live(self) -> None:
        """Live logs no replay claimed within a day are kept on the share too (raw/live/unmatched/)."""
        for folder, meta in completed_battles(self.live_root):
            if time.time() - meta["ended"] > UNMATCHED_LIVE_AFTER_S:
                self.share.put_tree(folder, f"raw/live/unmatched/{folder.name}")
                shutil.rmtree(folder)

    def _step_server(self, job: Job) -> bool:
        try:
            fetch_server_replay(job.session, self._dir(job) / "server")
            job.server = "done"
            return True
        except NotAvailableYet:
            job.server_attempts += 1
            old = time.time() - datetime.fromisoformat(job.started).timestamp() > SERVER_GONE_AFTER_S
            if old or job.server_attempts >= len(SERVER_RETRY_DELAYS):
                job.server = "missing"
                return True
            job.next_try = time.time() + SERVER_RETRY_DELAYS[job.server_attempts]
            return False

    def _step_raw_server(self, job: Job) -> bool:
        if job.server == "done":
            rel = f"raw/replays/server/{job.session}"
            job.hashes.update({f"{rel}/{k}": v for k, v in self.share.put_tree(self._dir(job) / "server", rel).items()})
        return True

    def _step_decode(self, job: Job) -> bool:
        folder = self._dir(job)
        out = folder / "decoded"
        shutil.rmtree(out, ignore_errors=True)
        inputs = {s: sorted((folder / s).glob("*.wrpl")) for s in ("client", "server")}
        result = decode_battle(inputs, out, self.cfg.me_user_id, should_stop=self._should_pause)
        job.result = asdict(result)
        (out / "result.json").write_text(json.dumps(job.result, indent=1), encoding="utf-8")
        return True

    def _step_publish(self, job: Job) -> bool:
        rel = f"decoded/{DECODER_ID}/{job.session}"
        job.hashes.update({f"{rel}/{k}": v for k, v in self.share.put_tree(self._dir(job) / "decoded", rel, overwrite=True).items()})
        return True

    def _step_manifest(self, job: Job) -> bool:
        tmp = self._dir(job) / "manifest.json"
        tmp.write_text(json.dumps(asdict(job), indent=1), encoding="utf-8")
        self.share.put(tmp, f"manifest/{job.session}.json", overwrite=True)
        return True

    def _step_summary(self, job: Job) -> bool:
        result = job.result or {}
        row = {
            **(result.get("summary") or {"started": job.started, "map": job.map, "replay_version": job.replay_version}),
            "server_status": job.server,
            "decode_status": "done" if result.get("sources") else "failed",
            "decode_error": "\n".join(f"{s}: {e}" for s, e in (result.get("errors") or {}).items()) or None,
            "decoder": result.get("decoder"),
            "schema_version": result.get("schema_version"),
        }
        self.api.put_match(job.session, row)
        return True

    # --- persistence

    def _dir(self, job: Job) -> Path:
        return self.cfg.staging / job.session

    def _save(self, job: Job) -> None:
        path = self._dir(job) / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(job), indent=1), encoding="utf-8")
        tmp.replace(path)

    def _load(self, folder: Path) -> Job:
        return Job(**json.loads((folder / "state.json").read_text(encoding="utf-8")))
