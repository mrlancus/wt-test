"""`wt-helper` command line. The background service (`run`) arrives with the live logger and watcher."""

from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

from wt_analytics.common.config import Config
from wt_analytics.helper.ingest import Queue


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()  # the decoder runs in child processes, also from the frozen exe
    ap = argparse.ArgumentParser(prog="wt-helper")
    ap.add_argument("--config", type=Path, help="config file (default: %%APPDATA%%\\wt-analytics\\config.toml)")
    sub = ap.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="queue client replays (.wrpl files or folders of them) and process them")
    ingest.add_argument("paths", nargs="+", type=Path)
    sub.add_parser("process", help="pull website uploads and advance every queued battle that is due")
    args = ap.parse_args(argv)

    queue = Queue(Config.load(args.config))
    if args.command == "ingest":
        for path in args.paths:
            for replay in sorted(path.glob("*.wrpl")) if path.is_dir() else [path]:
                job = queue.add(replay)
                print(f"queued {replay.name}: {job.map} {job.started} session {job.session}")
    else:
        print(f"{queue.pull_inbox()} uploads pulled from the website")
    for job in queue.run_due():
        state = "done" if job.done[-1:] == ["summary"] else f"waiting ({job.last_error or 'server replay not there yet'})"
        print(f"{job.session} {job.map}: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
