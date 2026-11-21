"""
Writing to the desk-hub share safely: copy to a temp name, verify the hash, then rename.
Re-copying an identical file is a no-op; a different file under an existing raw name is refused.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

_CHUNK = 1 << 20


class ShareOffline(Exception):
    """The share is not reachable; the caller keeps the data in staging and retries later."""


class ShareConflict(Exception):
    """A different file already exists under this name (raw files are never overwritten)."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


class Share:
    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self) -> None:
        if not self.root.is_dir():
            raise ShareOffline(f"share not reachable at {self.root}")

    def put(self, src: Path, rel: str, overwrite: bool = False) -> str:
        """Copy `src` to `<root>/<rel>`; returns its sha256. `overwrite` only for derived files."""
        self.check()
        digest = sha256(src)
        dst = self.root / rel
        if dst.exists():
            if dst.stat().st_size == src.stat().st_size and sha256(dst) == digest:
                return digest
            if not overwrite:
                raise ShareConflict(f"{rel} exists with different content")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
        try:
            shutil.copyfile(src, tmp)
            if sha256(tmp) != digest:
                raise OSError(f"hash mismatch after copying {rel}")
            os.replace(tmp, dst)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            if not self.root.is_dir():
                raise ShareOffline(str(e)) from e
            raise
        return digest

    def put_tree(self, src: Path, rel: str, overwrite: bool = False) -> dict[str, str]:
        """Copy every file under `src` to `<root>/<rel>/…`; returns {relative path: sha256}."""
        return {
            p.relative_to(src).as_posix(): self.put(p, f"{rel}/{p.relative_to(src).as_posix()}", overwrite)
            for p in sorted(src.rglob("*"))
            if p.is_file()
        }
