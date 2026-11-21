"""The one config file: %APPDATA%\\wt-analytics\\config.toml on Windows (or $WT_CONFIG)."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


def config_path() -> Path:
    if env := os.environ.get("WT_CONFIG"):
        return Path(env)
    base = os.environ.get("APPDATA") if sys.platform == "win32" else os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base or Path.home()) / "wt-analytics" / "config.toml"


@dataclass(frozen=True)
class Config:
    share: Path  # the desk-hub share, e.g. W:\wt — raw replays and decoded tables live here
    staging: Path  # small local queue on the PC; everything in it is on its way to the share
    replays: Path | None  # the game's Replays folder (None: not watched)
    api_url: str  # the website, e.g. https://wt-analytics.lancus.workers.dev
    api_key: str
    me_user_id: str

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        raw = tomllib.loads((path or config_path()).read_text(encoding="utf-8"))
        paths, api = raw.get("paths", {}), raw.get("api", {})
        return cls(
            share=Path(paths["share"]),
            staging=Path(paths.get("staging", "D:/wt-staging")),
            replays=Path(paths["replays"]) if paths.get("replays") else None,
            api_url=api["url"].rstrip("/"),
            api_key=api["key"],
            me_user_id=str(raw["player"]["user_id"]),
        )
