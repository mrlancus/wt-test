"""The decoder speed-ups must give byte-identical results to the original code, on real replays."""

from pathlib import Path

import pytest

from heat3d_ext_warthunder import cli, wrpl
from wt_analytics.pipeline import accel

GROUND_SERVER = Path(__file__).parent / "fixtures" / "server" / "72c412c100155b25"


@pytest.mark.skipif(not GROUND_SERVER.exists(), reason="real replay fixture not present")
def test_rle_matches_original_on_every_ground_delta(tmp_path, monkeypatch):
    original = wrpl._rle
    deltas: list[bytes] = []

    def record(src: bytes) -> bytes:
        deltas.append(bytes(src))
        return original(src)

    monkeypatch.setenv("HEAT3D_NO_UPDATE", "1")
    monkeypatch.setattr(wrpl, "_rle", record)
    assert cli.main([str(GROUND_SERVER), "-o", str(tmp_path), "--loose"]) == 0
    assert len(deltas) > 100_000
    assert all(accel.rle(d) == original(d) for d in deltas)


def test_rle_rejects_what_the_original_rejects():
    for bad in (b"", b"\x00\x01", bytes([0x05])):
        with pytest.raises(wrpl.FormatError):
            wrpl._rle(bad)
        with pytest.raises(wrpl.FormatError):
            accel.rle(bad)
