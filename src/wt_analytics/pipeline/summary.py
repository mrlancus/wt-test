"""One row per battle for the match list (D1 `matches`), from the decoder's match document."""

from __future__ import annotations

from typing import Any


def match_summary(doc: dict[str, Any], me_user_id: str) -> dict[str, Any]:
    """Map, mode, start, duration, my vehicles, my score line and the result, for player `me_user_id`."""
    battle = doc.get("battle", {})
    me = next((p for p in doc.get("players", []) if str(p.get("userId")) == me_user_id), None)
    result = doc.get("result", {})
    winner = result.get("winner")
    my_team = str(me["team"]) if me else None
    mrank = (doc.get("results", {}).get("matchingInfo", {}).get(me_user_id) or {}).get("mrank")
    return {
        "session": doc["sessionId"],
        "started": doc.get("started"),
        "map": doc.get("map"),
        "mission": doc.get("mission"),
        "game_mode": battle.get("gameMode"),
        "difficulty": battle.get("difficulty"),
        "mission_mode": battle.get("missionMode"),
        "duration_s": doc.get("timePlayed"),
        "replay_version": doc.get("replayVersion"),
        "mrank": mrank,
        "vehicles": me.get("vehicles", []) if me else [],
        "country": me.get("country") if me else None,
        "kills": _sum(me, "kills", "groundKills", "navalKills"),
        "ai_kills": _sum(me, "aiKills", "aiGroundKills", "aiNavalKills"),
        "assists": me.get("assists") if me else None,
        "deaths": me.get("deaths") if me else None,
        "captures": me.get("captureZone") if me else None,
        "score": me.get("score") if me else None,
        "result": None if winner is None or my_team is None else ("win" if winner == my_team else "loss"),
        "end_reason": result.get("endReason"),
    }


def _sum(player: dict[str, Any] | None, *keys: str) -> int | None:
    return sum(int(player.get(k) or 0) for k in keys) if player else None
