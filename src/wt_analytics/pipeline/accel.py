"""
Faster drop-in replacements for hot spots of the pinned 3DHeat decoder.

Applied only to the exact decoder version they were written and checked against
(`CHECKED_VERSION`); any other version runs unpatched. Each replacement must return
byte-identical results (checked by `tests/test_accel.py` on real replays).
"""

from __future__ import annotations

import numpy as np

import heat3d_ext_warthunder as heat3d
from heat3d_ext_warthunder import wrpl

CHECKED_VERSION = "0.2.2"
_WEIGHTS = np.array([1, 4, 16, 64], dtype=np.uint8)
_MAX_OUT = 65536


def rle(src: bytes) -> bytes:
    """`wrpl._rle`, the ground deltas' 2-bit run-length code, emitting runs in bulk."""
    last = len(src) - 1
    if last < 0 or src[last] not in (111, 222):
        raise wrpl.FormatError("not a ground delta")
    syms = bytearray()
    code = keep = -1
    one_last = src[last] == 111
    for i in range(last):
        b = src[i]
        for k in (0,) if (one_last and i == last - 1) else (0, 1):
            v0, v1 = (b >> (k * 4)) & 3, (b >> (2 + k * 4)) & 3
            if code != 4:
                code = v0
            if code == 0:
                syms += bytes(v1 + 3)
            elif code == 3:
                syms += bytes(v1 + 7)
            elif code == 1:
                code, keep = 4, v1
                syms.append(v1)
            elif code == 2:
                syms.append(v1)
            else:
                code = -1
                if keep == 0 and v0 == 0 and v1 == 0:
                    syms += bytes(39)
                else:
                    syms.append(v0)
                    syms.append(v1)
    # The original stops once its whole bytes exceed the limit; output only grows, so checking at the end is the same.
    if len(syms) // 4 > _MAX_OUT:
        raise wrpl.FormatError("ground delta too long")
    pad = -len(syms) % 4
    arr = np.frombuffer(bytes(syms) + bytes(pad), dtype=np.uint8).reshape(-1, 4)
    return (arr @ _WEIGHTS).astype(np.uint8).tobytes()


def install() -> bool:
    """Patch the decoder in place if its version is the checked one. Returns whether it did."""
    if heat3d.__version__ != CHECKED_VERSION:
        return False
    wrpl._rle = rle
    return True
