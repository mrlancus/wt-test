"""`wt-helper install`: write the config and start the service at every logon (Windows Task Scheduler)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TASK = "wt-helper"
DEFAULT_URL = "https://wt-analytics.lancus.workers.dev"


def write_config(path: Path, share: str, key: str, user_id: str, url: str, staging: str, replays: str | None) -> None:
    q = json.dumps  # a JSON string is a valid TOML basic string
    lines = [
        "[paths]",
        f"share = {q(share)}",
        f"staging = {q(staging)}",
        *([f"replays = {q(replays)}"] if replays else []),
        "",
        "[api]",
        f"url = {q(url)}",
        f"key = {q(key)}",
        "",
        "[player]",
        f"user_id = {q(user_id)}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def register_logon_task() -> str:
    """Runs `wt-helper run` at logon, hidden (conhost --headless), at normal user rights."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("autostart is set up by the Windows exe (wt-helper.exe install)")
    command = f'conhost.exe --headless "{sys.executable}" run'
    subprocess.run(["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "ONLOGON", "/RL", "LIMITED", "/TR", command], check=True, capture_output=True)
    subprocess.run(["schtasks", "/Run", "/TN", TASK], check=True, capture_output=True)
    return command


def remove_logon_task() -> None:
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK], check=True, capture_output=True)
