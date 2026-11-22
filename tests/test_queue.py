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

    def fake_decode(inputs, out, me, **_):
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



@pytest.mark.skipif(not AIR_CLIENT.exists(), reason="real replay fixture not present")
def test_battle_start_interrupts_decode_and_live_log_is_matched(tmp_path, monkeypatch):
    (tmp_path / "share").mkdir()
    cfg = Config(share=tmp_path / "share", staging=tmp_path / "staging", replays=None, api_url="http://x", api_key="k", me_user_id="1")
    monkeypatch.setattr(ingest, "fetch_server_replay", fake_fetch_missing)
    in_battle = {"now": False}
    decodes = []

    def fake_decode(inputs, out, me, should_stop):
        decodes.append(1)
        if len(decodes) == 1:
            in_battle["now"] = True  # a battle starts while the first decode runs
        if should_stop():
            raise ingest.Interrupted
        (out / "client").mkdir(parents=True)
        return BattleResult("heat3d-0.2.2", 1, sources={"client": []}, summary={"map": "air_afghan"})

    monkeypatch.setattr(ingest, "decode_battle", fake_decode)
    queue = ingest.Queue(cfg, FakeApi())
    job = queue.add(AIR_CLIENT)
    job.server_attempts = len(ingest.SERVER_RETRY_DELAYS) - 1  # last try: decode without the server replay
    started = ingest.datetime.fromisoformat(job.started).timestamp()
    for name, offset in (("this", 40), ("other", 4000)):  # this battle's live log, and a later battle's
        folder = queue.live_root / name
        folder.mkdir()
        (folder / "state.jsonl.zst").write_bytes(name.encode())
        (folder / "meta.json").write_text(f'{{"started": {started + offset}, "ended": {started + offset + 300}}}')

    pause = lambda: in_battle["now"]
    queue.advance(job, pause)
    assert "decode" not in job.done and job.last_error is None and job.next_try <= ingest.time.time()
    in_battle["now"] = False
    queue.advance(job, pause)
    assert job.done == list(ingest.STEPS) and len(decodes) == 2
    assert job.live == "this" and (cfg.share / f"raw/live/{job.session}/state.jsonl.zst").read_bytes() == b"this"
    assert (queue.live_root / "other" / "meta.json").exists()


def fake_fetch_missing(session, into):
    raise ingest.NotAvailableYet()


@pytest.mark.skipif(not AIR_CLIENT.exists(), reason="real replay fixture not present")
def test_redecode_restages_a_stored_battle_from_the_share(tmp_path, monkeypatch):
    (tmp_path / "share").mkdir()
    cfg = Config(share=tmp_path / "share", staging=tmp_path / "staging", replays=None, api_url="http://x", api_key="k", me_user_id="1")

    def fetch(session, into):
        into.mkdir(parents=True, exist_ok=True)
        (into / "0000.wrpl").write_bytes(b"part0")

    failed = BattleResult("heat3d-0.2.2", 1, errors={"client": "OSError", "server": "OSError"})
    monkeypatch.setattr(ingest, "fetch_server_replay", fetch)
    monkeypatch.setattr(ingest, "decode_battle", lambda inputs, out, me, should_stop: failed)
    queue = ingest.Queue(cfg, FakeApi())
    session = queue.add(AIR_CLIENT).session
    queue.run_due()
    assert not (cfg.staging / session).exists() and queue.stored_sessions(failed_only=True) == [session]

    seen = {}

    def decode_ok(inputs, out, me, should_stop):
        seen.update({s: [p.read_bytes() for p in files] for s, files in inputs.items()})
        (out / "server").mkdir(parents=True)
        return BattleResult("heat3d-0.2.2", 1, sources={"server": []}, summary={"map": "air_afghan"})

    monkeypatch.setattr(ingest, "decode_battle", decode_ok)
    job = queue.redecode(session)
    assert job.done == list(ingest.STEPS[:4])
    queue.run_due()
    assert seen == {"client": [AIR_CLIENT.read_bytes()], "server": [b"part0"]}
    assert queue.stored_sessions(failed_only=True) == []
