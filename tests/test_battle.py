"""Stopping a decode when a battle starts must kill the decoder processes at once."""

import time
from pathlib import Path

import pytest

from wt_analytics.pipeline import battle

GROUND_SERVER = sorted((Path(__file__).parent / "fixtures" / "server" / "72c412c100155b25").glob("*.wrpl"))


@pytest.mark.skipif(not GROUND_SERVER, reason="real replay fixture not present")
def test_should_stop_kills_the_decode(tmp_path):
    began = time.monotonic()
    with pytest.raises(battle.Interrupted):
        battle.decode_battle({"server": GROUND_SERVER}, tmp_path, "1", should_stop=lambda: time.monotonic() - began > 2)
    assert time.monotonic() - began < 6  # a full decode takes ~100 s
