"""`wt-helper` command line: `install`, `run` (the background service), `doctor`, `ingest`, `process`."""

from __future__ import annotations

import argparse
import multiprocessing
import sys
from pathlib import Path

from wt_analytics.common.config import Config, config_path


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()  # the decoder runs in child processes, also from the frozen exe
    ap = argparse.ArgumentParser(prog="wt-helper")
    ap.add_argument("--config", type=Path, help="config file (default: %%APPDATA%%\\wt-analytics\\config.toml)")
    sub = ap.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install", help="write the config and start wt-helper at every logon")
    install.add_argument("--share", required=True, help='the desk-hub share, e.g. "W:/"')
    install.add_argument("--key", required=True, help="the website key")
    install.add_argument("--user-id", required=True, help="your War Thunder userId")
    install.add_argument("--url", default=None, help="the website (default: the wt-analytics site)")
    install.add_argument("--staging", default="D:/wt-staging", help="local queue folder (default D:/wt-staging)")
    install.add_argument("--replays", default=None, help="the game's Replays folder (default: found automatically)")
    sub.add_parser("uninstall", help="stop starting wt-helper at logon (keeps config and data)")
    sub.add_parser("run", help="the background service: record battles, queue replays, process between battles")
    sub.add_parser("doctor", help="check the share, website, game folder and queue")
    ingest = sub.add_parser("ingest", help="queue client replays (.wrpl files or folders of them) and process them")
    ingest.add_argument("paths", nargs="+", type=Path)
    sub.add_parser("process", help="pull website uploads and advance every queued battle that is due")
    args = ap.parse_args(argv)
    path = args.config or config_path()

    if args.command == "install":
        from wt_analytics.helper import autostart

        autostart.write_config(path, args.share, args.key, args.user_id, args.url or autostart.DEFAULT_URL, args.staging, args.replays)
        print(f"config written to {path}")
        print(f"autostart: {autostart.register_logon_task()}")
        return 0
    if args.command == "uninstall":
        from wt_analytics.helper import autostart

        autostart.remove_logon_task()
        print("autostart removed")
        return 0

    cfg = Config.load(path)
    if args.command == "run":
        from wt_analytics.helper.service import run, setup_logging

        setup_logging(cfg)
        run(cfg)
        return 0
    if args.command == "doctor":
        from wt_analytics.helper.doctor import doctor

        return 0 if doctor(cfg) else 1

    from wt_analytics.helper.ingest import Queue

    queue = Queue(cfg)
    if args.command == "ingest":
        for p in args.paths:
            for replay in sorted(p.glob("*.wrpl")) if p.is_dir() else [p]:
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
