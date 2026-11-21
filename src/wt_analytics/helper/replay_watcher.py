"""
Finds new client replays in the game's Replays folder. A replay is taken once its size has not
changed for `STABLE_S` seconds (the game has finished writing it). Names starting with `#` are
replays the game is still writing (header still zero), or leftovers of a crash: never taken. Replays already there when
the helper first ran are not taken automatically (`wt-helper ingest <folder>` imports a backlog).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STABLE_S = 10.0


def find_replays_folder(configured: Path | None) -> Path | None:
    """The configured folder, else `<War Thunder>/Replays` of the install found on this PC."""
    if configured:
        return configured
    from heat3d_ext_warthunder.install import find_game

    game = find_game()
    return game / "Replays" if game else None


class ReplayWatcher:
    def __init__(self, folder: Path, seen_file: Path) -> None:
        self.folder = folder
        self._seen_file = seen_file
        self._sizes: dict[str, tuple[int, float]] = {}  # name -> (size, when it last changed)
        if seen_file.exists():
            self._seen = set(json.loads(seen_file.read_text(encoding="utf-8")))
        else:  # first run: what is there already is history, not new battles
            self._seen = {p.name for p in folder.glob("*.wrpl")}
            self._save()

    def new_replays(self) -> list[Path]:
        """Replays that appeared since last time and are finished; call `taken()` once each is queued."""
        now = time.monotonic()
        ready = []
        for path in sorted(self.folder.glob("*.wrpl")):
            if path.name in self._seen or path.name.startswith("#"):  # "#…": the game is still writing it
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            previous = self._sizes.get(path.name)
            if previous is None or previous[0] != size:
                self._sizes[path.name] = (size, now)
            elif now - previous[1] >= STABLE_S and size > 0:
                ready.append(path)
        return ready

    def taken(self, path: Path) -> None:
        self._seen.add(path.name)
        self._sizes.pop(path.name, None)
        self._save()

    def _save(self) -> None:
        self._seen_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._seen_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(self._seen)), encoding="utf-8")
        tmp.replace(self._seen_file)
