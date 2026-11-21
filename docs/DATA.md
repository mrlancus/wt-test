# Data sources — what they really contain

Status markers: **[verified]** checked on the user's own data · **[documented]** stated by the
tool's docs/code, not yet checked by us · **[unknown]** to find out.
Nothing here is verified yet: Phase 0 is waiting for real files (see `PHASE0.md`).

## 1. Local API, `http://127.0.0.1:8111`
Read-only web server the game runs while open. Endpoints to confirm from the page's JS with
`tools/dump-8111.ps1` **[unknown]**: `/state`, `/indicators`, `/map_obj.json`, `/map_info.json`,
`/mission.json`, `/hudmsg?lastEvt=N&lastDmg=N`, `/gamechat?lastId=N`, `/map.img`, `/info`.
- `map_obj.json` holds only what the player's minimap shows (spotted enemies, team, objectives).
- Battle start/end detection: `/indicators.valid`, `/map_info.json.valid`, mission status **[unknown]**.
- The session id is **not** expected to be exposed here **[unknown]**; we take it from the client replay.

## 2. Client replays (`.wrpl`, game's `Replays` folder)
Header (3DHeat `wrpl.py`) **[documented]**:
| Offset | Type | Field |
|---|---|---|
| 0 | u32 | magic `0x1000ACE5` |
| 4 | u32 | replay version (game build, e.g. 101404) |
| 8 | 128 B | level `levels/<map>.bin` |
| 396 | 128 B | battle type |
| 688 | u8 | difficulty |
| 732 | u64 | **session id** (shown as 16-digit hex) |
| 740 | u8 | part number (server replays) |
| 908 | u32 | start time, Unix s |
| 968 | 128 B | battle class (`base_dom`, …) |
Then mission settings blk, a packet stream (zstd in 2026 builds, zlib in 2025), and a results blk.

Contents **[documented]**: every aircraft's position/attitude ~4/s; ground units' positions,
attitude and turrets; the recording player's camera ~20/s (quaternion, zoom; no FOV in
degrees) and aim (`aimHeading/aimPitch/aimDistance`); the recording player's cockpit
instruments and controls (aircraft only); kills, hits, damage, module destruction, weapon
releases, missiles/rockets/bombs in flight, chat, awards, results.
The client is not sent every kill; the results table has the true counts.

## 3. Server replays (`https://wt-game-replays.warthunder.com/<session_hex>/NNNN.wrpl`)
- Download: plain `GET`, no auth; parts `0000.wrpl`, `0001.wrpl`, … until 404/403
  (wrpl-inspector's downloader). Host reachable from cloud IPs (got 404 for a fake id) **[verified]**.
- Session id is the header's u64 at offset 732 as 16-digit lowercase hex. The website's replay
  page uses the same number in decimal: `https://warthunder.com/en/tournament/replay/<decimal>`.
- When a replay becomes available after the battle, and for how long, **[unknown]**.
- Contents **[documented]**: every tank's state incl. turret, **every player's camera ~8/s**
  (`viewYaw`, `viewPitch`, `zoom`, `cameraMode`), every player's slots and stats.
  Aircraft in 2025-era server replays are *not* decoded.

## 4. Decoder output (3DHeat-Ext-WarThunder 0.2.2, MIT)
Pure Python (pyarrow, numpy, zstandard, pillow), runs on Linux **[documented]**. Oodle (a game
DLL) is needed only for level/terrain extraction, not for replays. The install is used for
English names and economy prices. Auto-updates on start unless `HEAT3D_NO_UPDATE=1`.
Outputs, per battle: `<match>.parquet` (one row per sample/event, 105 columns),
`<match>.match.json`, `.messages.parquet`, `.objectives.parquet`, `.flight.parquet`.
`<match>` = `<map>_<AB|RB|SB>_<mode>_<start UTC>_<session id>`.

Conventions **[documented]**:
- `x` east, `y` up, `z` north, metres. `time` in seconds on the replay's clock.
- `viewYaw`/`aimHeading`: world compass degrees (0 = north, clockwise); `viewPitch` degrees up.
- `turretYaw`: **relative to the hull**, clockwise; `turretYaw` is smoothed to the turret drive
  speed, the replay's value is `turretYawRaw`.
- `extrapolated` marks dead-reckoned samples; `*Raw` columns hold values before smoothing.
- Tracks are cut at teleports (`trackBreaks`), wrecks are `alive = 0`.

Not in the replay at all **[documented]**: camera FOV in degrees (only zoom), module names for
destroyed parts (need the damage model).

## 5. Terrain and levels (helper, PC only)
3DHeat's `heat3d-wt-level` builds heightmaps and objects (forests, towns) from the install,
needs the game's Oodle DLL. Whether it can hand us a raw heightmap array + object
footprints for LOS (instead of only a `.glb`) **[unknown]** — Phase 0 step 4.
