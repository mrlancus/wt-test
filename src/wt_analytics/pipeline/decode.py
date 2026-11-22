"""
Decode one battle's replay files with the pinned 3DHeat decoder and split the wide table
into per-event Parquet tables (sorted by track, time; columns that are empty in a table dropped).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import duckdb

from wt_analytics.common.schema import DECODER_VERSION, EVENT_TABLES, OTHER_TABLE, SIDECARS
from wt_analytics.pipeline import accel

os.environ.setdefault("HEAT3D_NO_UPDATE", "1")

import heat3d_ext_warthunder as heat3d  # noqa: E402  (after HEAT3D_NO_UPDATE is set)
from heat3d_ext_warthunder import cli as heat3d_cli  # noqa: E402


class DecodeError(Exception):
    """The decoder did not produce a battle from the given files."""


@dataclass(frozen=True)
class Decoded:
    """Files written for one replay source (client or server) of a battle."""

    match_name: str
    files: list[Path]


def check_version() -> None:
    if heat3d.__version__ != DECODER_VERSION:
        raise DecodeError(f"decoder {heat3d.__version__} installed, {DECODER_VERSION} pinned")


def decode(inputs: list[Path], out: Path) -> Decoded:
    """Decode the replay files of one source (one client .wrpl, or a server replay's parts) into `out`."""
    check_version()
    accel.install()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix=".decode-") as tmp:  # same drive as `out`
        status = heat3d_cli.main([*map(str, inputs), "-o", tmp, "--loose"])
        tables = [p for p in Path(tmp).rglob("*.parquet") if p.name.count(".") == 1]
        if status != 0 or len(tables) != 1:
            raise DecodeError(f"decoder exit {status}, {len(tables)} battles from {[p.name for p in inputs]}")
        table = tables[0]
        name = table.stem
        out.mkdir(parents=True, exist_ok=True)
        files = split_events(table, out)
        for suffix in SIDECARS:
            src = table.with_name(f"{name}.{suffix}")
            if src.exists():
                dst = out / suffix
                shutil.move(src, dst)
                files.append(dst)
    return Decoded(name, files)


def split_events(table: Path, out: Path) -> list[Path]:
    """Write one zstd Parquet file per event group, keeping only the columns that hold data in that group."""
    con = duckdb.connect()
    con.execute(f"create view t as select * from read_parquet('{table}')")
    columns = [r[0] for r in con.execute("describe t").fetchall()]
    listed = [e for events in EVENT_TABLES.values() for e in events]
    groups = {name: f"event in {_sql_list(events)}" for name, events in EVENT_TABLES.items()}
    groups[OTHER_TABLE] = f"event not in {_sql_list(listed)}"
    written = []
    for name, where in groups.items():
        keep = _filled_columns(con, columns, where)
        if not keep:
            continue
        path = out / f"{name}.parquet"
        select = ", ".join(f'"{c}"' for c in keep)
        con.execute(
            f"copy (select {select} from t where {where} order by track, time) "
            f"to '{path}' (format parquet, compression zstd)"
        )
        written.append(path)
    return written


def _filled_columns(con: duckdb.DuckDBPyConnection, columns: list[str], where: str) -> list[str]:
    """Columns with at least one non-null, non-empty value among the rows matching `where` (empty if no rows)."""
    probes = ", ".join(f"count(nullif(\"{c}\"::varchar, ''))" for c in columns)
    row = con.execute(f"select count(*), {probes} from t where {where}").fetchone()
    if not row[0]:
        return []
    always = {"time", "event", "track"}
    return [c for c, n in zip(columns, row[1:]) if n or c in always]


def _sql_list(values: tuple[str, ...] | list[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"
