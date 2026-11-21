"""`wt-helper doctor`: checks everything the helper depends on and says what is wrong."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import httpx

from wt_analytics.common.config import Config
from wt_analytics.helper.api import Api
from wt_analytics.helper.live_logger import BASE, completed_battles
from wt_analytics.helper.replay_watcher import find_replays_folder


def doctor(cfg: Config) -> bool:
    checks: list[tuple[str, Callable[[], str]]] = [
        ("decoder", _decoder),
        ("share", lambda: _share(cfg.share)),
        ("staging", lambda: _staging(cfg.staging)),
        ("replays folder", lambda: _replays(cfg.replays)),
        ("website", lambda: _website(cfg)),
        ("game API (8111)", _game_api),
        ("queue", lambda: _queue(cfg.staging)),
    ]
    ok = True
    for name, check in checks:
        try:
            print(f"  ok    {name}: {check()}")
        except Exception as e:
            ok = False
            print(f"  FAIL  {name}: {e}")
    return ok


def _decoder() -> str:
    from wt_analytics.pipeline.decode import check_version
    from wt_analytics.common.schema import DECODER_VERSION

    check_version()
    return f"3DHeat {DECODER_VERSION} (pinned)"


def _share(root: Path) -> str:
    if not root.is_dir():
        raise RuntimeError(f"{root} not reachable (is W: mapped? `net use W: \\\\deskhub.local\\wt /user:wtshare /persistent:yes`)")
    probe = root / f".doctor-{id(root)}.tmp"
    probe.write_bytes(b"ok")
    probe.unlink()
    return f"{root} writable, {shutil.disk_usage(root).free / 2**30:.0f} GB free"


def _staging(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    return f"{root}, {shutil.disk_usage(root).free / 2**30:.0f} GB free"


def _replays(configured: Path | None) -> str:
    folder = find_replays_folder(configured)
    if not folder or not folder.is_dir():
        raise RuntimeError("War Thunder's Replays folder not found: set [paths] replays in the config, and turn on saving replays in the game")
    return f"{folder} ({len(list(folder.glob('*.wrpl')))} replays)"


def _website(cfg: Config) -> str:
    health = Api(cfg).health()
    return f"{cfg.api_url} key accepted, {json.dumps(health)}"


def _game_api() -> str:
    try:
        httpx.get(f"{BASE}/map_info.json", timeout=1).raise_for_status()
        return "answering"
    except httpx.HTTPError:
        return "not answering (fine unless the game is running)"


def _queue(staging: Path) -> str:
    jobs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(staging.glob("*/state.json"))]
    lines = [f"{len(jobs)} battles in progress, {len(completed_battles(staging / 'live'))} live logs waiting for a replay"]
    lines += [f"\n          {j['session']} {j['map']}: done {','.join(j['done']) or '-'}; {j['last_error'] or ''}" for j in jobs]
    return "".join(lines)
