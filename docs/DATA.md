# Data sources — what they really contain

Status markers: **[verified]** checked on the user's own data · **[documented]** stated by the
tool's docs/code, not yet checked by us · **[unknown]** to find out.

Verified on (2026-11-21), game replay version **101421**, decoder 3DHeat-Ext-WarThunder **0.2.2**:
- Air RB, `air_afghan` (BfD, no respawn), Su-30SM, session `72c412c1000ffbd9`: client + server.
- Ground RB, `avg_africa_desert` (Domination), BMPT-72 (+ Ka-50 in lineup, unused), session
  `72c412c100155b25`: client + server.

## 1. Local API, `http://127.0.0.1:8111`
Not inspected yet; deferred to the helper (it will discover endpoints from the page JS and store
every raw response). Known/expected endpoints: `/state`, `/indicators`, `/map_obj.json`,
`/map_info.json`, `/mission.json`, `/hudmsg?lastEvt=N&lastDmg=N`, `/gamechat?lastId=N`, `/map.img`.
`map_obj.json` holds only what the minimap shows. The map image + `map_info.json` are needed for
2D map alignment. **[unknown]**

## 2. Identifying me **[verified]**
- Client replay: match JSON `author` = `"[MNSTR] mrlancus"`, `authorUserId` = `110703665`.
- Server replay: no author. Match by **userId** (config value, learned from the first client replay).
- Table column `userId` (string) identifies my rows in both.

## 3. Client replays (`.wrpl`)
Header **[verified]** (offsets from 3DHeat `wrpl.py`): magic `0x1000ACE5`, u32 version @4,
level @8, battle type @396, difficulty @688, **session id u64 @732** (16-digit hex),
part @740, start time Unix s @908, time limit @912, battle class @968.
Sizes: 2.9 MB (air, 3 min), 3.4 MB (ground, 7 min).

Contents **[verified]**:
| | Client replay |
|---|---|
| Coverage | **Only until I leave the battle.** Air (no respawn): replay ends 184 s, at my death + a few s; the battle ran 503 s |
| My unit | ground ~23 Hz with `viewYaw` and turret 100 %; air ~4 Hz; cockpit instruments (`ias`, `throttle`, `rpm`) for my aircraft only, `fuel` empty |
| Other units | aircraft ~4 Hz; tanks **~3 Hz, no view direction, no turret** |
| Hits by me (`shot` rows) | target, vehicle, `ammoType`; **no outcome** (`hitOutcome` empty) |
| Camera | my own replay camera, ~20 rows/s (`kind='camera'`) |

## 4. Server replays **[verified]**
- URL `https://wt-game-replays.warthunder.com/<session_hex>/NNNN.wrpl` → **302 redirect** to
  `https://wt-replays-cdnnow.cdn.gaijin.net/<session_hex>/NNNN.wrpl`. No auth. Parts 0000…
  until **404**. Ground: 10 parts, 15 MB; air: 12 parts, 33 MB.
- Available ~30 min after the battle at the latest (ground fetched 30 min after; earliest unknown).
- The CDN is **flaky**: connection resets mid-sequence (part 0007/0009 failed, then worked on
  retry). A missing part is *not* the end; only 404/403 is. Needs per-part retries with backoff.
- The `warthunder.com/en/tournament/replay/<decimal id>` page needs a Gaijin login; the CDN does not.

Contents:
| | Server replay |
|---|---|
| Coverage | the **whole battle** (air: 503 s although I died at 154 s) |
| Tanks | **~24 Hz** for every tank, turret 100 %, `viewYaw/viewPitch` ~80 % of samples |
| Aircraft | ~4 Hz, view direction ~70–99 % |
| Missiles | full flight paths: air battle 173 missiles, 320k position rows |
| Hit outcomes | `hitOutcome` = `penetration` / `nonpenetration` / `critical` / `kill` (ground: 505 / 366 / 140 / 63) |
| Module destruction | `module_destroyed` rows (air battle: 156) — part number only, no name |
| My cockpit instruments | **not present** (only in the client replay) |
| Lineups / BR | `results.matchingInfo[userId]`: `mrank` and each vehicle in the lineup (`crafts_info`), e.g. `ussr_bmpt_72` mrank 33 |

**Conclusion:** the server replay is the primary source. The client replay adds my aircraft's
instruments, my camera, and the session id. Keep both.

## 5. Decoder output (3DHeat-Ext-WarThunder 0.2.2)
- Pure Python, runs on Linux without the game **[verified]**. Without an install, vehicles and
  weapons have ids only (`ussr_bmpt_72`, `us_aim_120c_5`, `120mm_jm33`); English names and
  economy prices need the install catalogue from the helper.
- Auto-update disabled with `HEAT3D_NO_UPDATE=1`.
- Files per battle: `<match>.parquet` (105 columns), `.match.json`, `.messages.parquet`,
  `.objectives.parquet`, `.flight.parquet`. Server outputs end in `_server`.
- Decoded size: ground server table 30 MB + 8.5 MB messages; air server 32 MB + 8.7 MB.
- Decode time (Xeon 2.1 GHz, one core per replay): client 10 s (air) / 24 s (ground); ground server
  105 s on Python 3.12 → **85 s** with Python 3.14 and the checked `_rle` speed-up (`pipeline/accel.py`).
  The rest is spread over pure-Python bit reading and table building (no single hot spot left).
  Client and server decode in parallel, so a battle takes ~100 s in the container.
- After the per-event split, the ground server tables are 14.8 MB positions + < 100 KB each for
  hits, kills, weapons, fires, logistics (from 29 MB as one table).

Conventions **[verified]** on the ground death (killer Type 90B, 520 m):
- `x` east, `z` north, `y` up, metres. Bearing from A to B = `atan2(Δx, Δz)` in compass degrees.
- `heading` is a compass heading; `turretYaw` is **hull-relative**, clockwise:
  `heading + turretYaw` equals the killer's `viewYaw` within ~0.5° while aiming.
- `viewYaw` is world compass degrees. The killer's view converged to < 1° on my bearing 3.5 s
  before the kill — "time aimed at me" is measurable.
- `event` values seen: `position, shot, gun_shot, launch, impact, explosion, kill, death, dead,
  despawn, hit_critical, hit_severe, module_destroyed, fire_start/stop, fire_on/off, reload,
  bullet_rearm, rearm, repair, bailout`.
- `shot` rows are **hits** (with target in `other`/`otherVehicle`), not trigger pulls. Rounds that
  hit nothing are not listed for tanks; aircraft guns appear as `gun_shot`. Whether my missed tank
  rounds can be counted at all **[unknown]** (likely not → accuracy would need another source).
- `hitPart` holds a numeric part id, not a name.

## 6. Terrain and levels (helper, PC only)
3DHeat's `heat3d-wt-level` builds heightmaps and objects from the install; it needs the game's
Oodle DLL (`oo2core_9_win64.dll`), so it can only run on the PC. Whether we can get a raw
heightmap array + object footprints for LOS (not just `.glb`) **[unknown]** — checked when the
helper's LOS module is built (Phase 3).
