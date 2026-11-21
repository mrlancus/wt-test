"""Versions and table layout shared by the pipeline, the Worker contract and the docs."""

from __future__ import annotations

DECODER = "heat3d"
DECODER_VERSION = "0.2.2"
#: Bump to re-derive everything (derived/<SCHEMA_VERSION>/...).
SCHEMA_VERSION = 1

#: Decoded tables: name -> the 3DHeat `event` values that go into it. Anything not listed goes to "other".
EVENT_TABLES: dict[str, tuple[str, ...]] = {
    "positions": ("position",),
    "hits": ("shot", "impact", "hit_critical", "hit_severe", "module_destroyed"),
    "kills": ("kill", "death", "dead", "despawn", "bailout"),
    "weapons": ("launch", "gun_shot", "explosion"),
    "fires": ("fire_start", "fire_stop", "fire_on", "fire_off"),
    "logistics": ("reload", "bullet_rearm", "rearm", "repair"),
}
OTHER_TABLE = "other"
#: 3DHeat sidecar files kept as they are (suffix after the match name).
SIDECARS = ("match.json", "messages.parquet", "objectives.parquet", "flight.parquet")
