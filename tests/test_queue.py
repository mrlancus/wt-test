"""The local queue must never lose a battle: an offline share delays it, and finished steps never repeat."""

from pathlib import Path

import pytest

from wt_analytics.common.config import Config
from wt_analytics.helper import ingest
from wt_analytics.helper.share import Share, ShareConflict
from wt_analytics.pipeline.battle import BattleResult

AIR_CLIENT = Path(__file__).parent / "fixtures" / "client" / "2026.11.20_17.58.02.wrpl"


class FakeApi:
    def __init__(self):
        self.rows = {}

    def put_match(self, session, row):
        self.rows[session] = row


def test_share_put_is_idempotent_and_never_overwrites_raw(tmp_path):
    share = Share(tmp_path / "share")
    (tmp_path / "share").mkdir()
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"replay one")
    b.write_bytes(b"replay two")
    assert share.put(a, "raw/x.wrpl") == share.put(a, "raw/x.wrpl")
    with pytest.raises(ShareConflict):
        share.put(b, "raw/x.wrpl")
    assert (tmp_path / "share/raw/x.wrpl").read_bytes() == b"replay one"
    assert not list((tmp_path / "share/raw").glob(".*.tmp"))


@pytest.mark.skipif(not AIR_CLIENT.exists(), reason="real replay fixture not present")
def test_offline_share_delays_without_losing_or_repeating(tmp_path, monkeypatch):
    share_root = tmp_path / "share"  # does not exist yet: the share is offline
    cfg = Config(share=share_root, staging=tmp_path / "staging", replays=None, api_url="http://x", api_key="k", me_user_id="110703665")
    calls = {"fetch": 0, "decode": 0}

    def fake_fetch(session, into):
        calls["fetch"] += 1
        into.mkdir(parents=True, exist_ok=True)
        (into / "0000.wrpl").write_bytes(b"part")
        return [into / "0000.wrpl"]

    def fake_decode(inputs, out, me):
        calls["decode"] += 1
        (out / "server").mkdir(parents=True)
        (out / "server" / "positions.parquet").write_bytes(b"table")
        return BattleResult("heat3d-0.2.2", 1, sources={"server": ["positions.parquet"]}, summary={"map": "air_afghan"})

    monkeypatch.setattr(ingest, "fetch_server_replay", fake_fetch)
    monkeypatch.setattr(ingest, "decode_battle", fake_decode)
    api = FakeApi()
    queue = ingest.Queue(cfg, api)
    job = queue.add(AIR_CLIENT)

    queue.advance(job)  # share offline: the first step fails, everything stays staged
    assert job.done == [] and "ShareOffline" in job.last_error
    assert (cfg.staging / job.session / "client" / f"{job.session}.wrpl").exists()
    assert not api.rows

    share_root.mkdir()  # share back
    queue.advance(job)
    assert job.done == list(ingest.STEPS)
    assert calls == {"fetch": 1, "decode": 1}
    assert (share_root / f"raw/replays/client/2026-11-20/{job.session}.wrpl").read_bytes() == AIR_CLIENT.read_bytes()
    assert (share_root / f"decoded/heat3d-0.2.2/{job.session}/server/positions.parquet").exists()
    assert api.rows[job.session]["server_status"] == "done"
    assert not (cfg.staging / job.session).exists()  # cleared only once all is on the share
