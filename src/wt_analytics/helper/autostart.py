"""`wt-helper install`: write the config and start the service at every logon (the user's Run key: no admin rights)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "wt-helper"
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
    """Runs `wt-helper run` at every logon, hidden (conhost --headless), and starts it now."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise RuntimeError("autostart is set up by the Windows exe (wt-helper.exe install)")
    import winreg

    command = f'conhost.exe --headless "{sys.executable}" run'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command)
    subprocess.Popen([sys.executable, "run"], creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
    return command


def remove_logon_task() -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, NAME)
