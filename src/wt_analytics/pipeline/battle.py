"""
Decode one battle: its client replay and/or server replay parts, in parallel processes,
plus the merged match summary. Runs on the gaming PC after the battle (low priority).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wt_analytics.common.schema import DECODER, DECODER_VERSION, SCHEMA_VERSION
from wt_analytics.pipeline.decode import decode
from wt_analytics.pipeline.summary import match_summary

DECODER_ID = f"{DECODER}-{DECODER_VERSION}"
POLL_S = 1.0


class Interrupted(Exception):
    """Decoding was stopped (a battle started); nothing usable was written, run it again later."""


@dataclass
class BattleResult:
    decoder: str
    schema_version: int
    sources: dict[str, list[str]] = field(default_factory=dict)  # source -> files written in out/<source>/
    errors: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] | None = None


def decode_battle(
    inputs: dict[str, list[Path]],
    out: Path,
    me_user_id: str,
    low_priority: bool = True,
    should_stop: Callable[[], bool] = lambda: False,
) -> BattleResult:
    """`inputs` maps "client"/"server" to that source's replay files; outputs go to out/<source>/.
    If `should_stop()` turns true, the decoder processes are killed and `Interrupted` is raised."""
    result = BattleResult(DECODER_ID, SCHEMA_VERSION)
    present = {s: files for s, files in inputs.items() if files}
    pool = ProcessPoolExecutor(max_workers=max(1, len(present)), initializer=_lower_priority if low_priority else None)
    try:
        futures = {s: pool.submit(decode, files, out / s) for s, files in present.items()}
        while wait(futures.values(), timeout=POLL_S).not_done:
            if should_stop():
                _kill(pool)
                raise Interrupted
        for source, future in futures.items():
            try:
                result.sources[source] = [p.name for p in future.result().files]
            except Exception as e:  # one bad source must not lose the other
                result.errors[source] = f"{type(e).__name__}: {e}"
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    result.summary = merged_summary(out, [s for s in ("server", "client") if s in result.sources], me_user_id)
    return result


def merged_summary(out: Path, sources: list[str], me_user_id: str) -> dict[str, Any] | None:
    """Summary from the first source (server: whole battle), gaps filled from the next (client: e.g. country)."""
    summaries = [match_summary(json.loads((out / s / "match.json").read_text(encoding="utf-8")), me_user_id) for s in sources]
    if not summaries:
        return None
    return {k: next((s[k] for s in summaries if s[k] not in (None, [])), summaries[0][k]) for k in summaries[0]}


def _kill(pool: ProcessPoolExecutor) -> None:
    if hasattr(pool, "kill_workers"):  # Python 3.14+
        pool.kill_workers()
    else:
        for process in list(getattr(pool, "_processes", {}).values()):
            process.kill()


def _lower_priority() -> None:
    """Decoding must not compete with the game: below-normal priority on Windows, nice 10 elsewhere."""
    import os
    import sys

    if sys.platform == "win32":
        import ctypes

        below_normal = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), below_normal)
    else:
        os.nice(10)
