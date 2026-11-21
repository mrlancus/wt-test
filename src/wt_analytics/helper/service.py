"""
`wt-helper run`: the background service. While a battle runs it only records the live log
(rule 1: nothing is uploaded or decoded during a battle; a running decode is stopped). Between
battles it queues new replays, pulls website uploads and works through the queue.
"""

from __future__ import annotations

import logging
import logging.handlers
import socket
import threading
import time

import httpx

from wt_analytics.common.config import Config
from wt_analytics.helper.ingest import Queue
from wt_analytics.helper.live_logger import LiveLogger
from wt_analytics.helper.replay_watcher import ReplayWatcher, find_replays_folder
from wt_analytics.helper.share import ShareOffline

log = logging.getLogger("wt_analytics")

TICK_S = 10.0
INBOX_EVERY_S = 120.0
SINGLE_INSTANCE_PORT = 48111  # held while the service runs, so a second copy exits at once


def setup_logging(cfg: Config) -> None:
    folder = cfg.staging / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / "helper.log", maxBytes=5 << 20, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)


def take_new(queue: Queue, watcher: ReplayWatcher) -> None:
    for replay in watcher.new_replays():
        try:
            job = queue.add(replay)
        except OSError as e:  # e.g. still locked by the game: try again next tick
            log.warning("cannot read %s yet: %s", replay.name, e)
            continue
        except Exception:  # not a replay we can read: don't try it again
            log.exception("skipping %s", replay.name)
        else:
            log.info("queued %s: %s %s", replay.name, job.map, job.session)
        watcher.taken(replay)


def run(cfg: Config, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    guard = socket.socket()
    try:
        guard.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        log.info("wt-helper is already running")
        return
    queue = Queue(cfg)
    logger = LiveLogger(queue.live_root)
    logger.start()
    folder = find_replays_folder(cfg.replays)
    watcher = ReplayWatcher(folder, cfg.staging / "seen-replays.json") if folder and folder.is_dir() else None
    log.info("running: share %s, replays %s", cfg.share, folder if watcher else "not found (website uploads only)")
    last_inbox = 0.0
    try:
        while not stop.wait(TICK_S):
            if logger.in_battle.is_set():
                continue
            try:
                if watcher:
                    take_new(queue, watcher)
                if time.monotonic() - last_inbox > INBOX_EVERY_S:
                    last_inbox = time.monotonic()
                    if added := queue.pull_inbox():
                        log.info("%d website uploads queued", added)
                for job in queue.run_due(should_pause=logger.in_battle.is_set):
                    log.info("%s %s: done %s%s", job.session, job.map, ",".join(job.done), f" ({job.last_error})" if job.last_error else "")
                queue.sweep_live()
            except (ShareOffline, httpx.HTTPError, OSError) as e:
                log.warning("will retry: %s: %s", type(e).__name__, e)
            except Exception:  # keep the service alive; the queue keeps its state on disk
                log.exception("unexpected error")
    finally:
        logger.stop()
        guard.close()
