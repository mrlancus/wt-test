# Architecture

**Desk-hub stores, the PC works, Cloudflare shows.** (Decided 2026-11-21, replacing an earlier
cloud-processing design: replays stay at home, Cloudflare gets only what the website needs.)

```
Gaming PC (Windows)                      desk-hub laptop               Cloudflare (private site)
┌──────────────────────────────┐  SMB    ┌───────────────────┐        ┌──────────────────────────┐
│ wt-helper                    │ ──────► │ Samba share  W:\  │        │ Worker: API + web pages  │
│  live_logger (8111)          │         │  wt/raw/…         │        │ D1: match rows           │
│  replay_watcher              │         │  wt/decoded/…     │        │ R2: inbox (website       │
│  server replay fetch         │         │  wt/manifest/…    │        │     uploads, until the   │
│  decode (3DHeat, low prio)   │         └───────────────────┘        │     PC has them),        │
│  local queue (staging, D:)   │ ── HTTPS: summaries, later viewer ──►│     later viewer packs   │
│  los (terrain, local only)   │ ◄─ HTTPS: website uploads ────────── │     and derived tables   │
└──────────────────────────────┘                                      └──────────────────────────┘
```

## Why this split
- **Replays and full decoded tables** are large (~50–70 MB a battle) and only needed for
  re-processing → the desk-hub share, which has plenty of disk. Desk-hub only serves files:
  no processing there (it runs Klipper and must not be starved).
- **Processing** needs the replays, and the PC has them already. Decoding a battle takes about
  a minute at low priority after the battle; it pauses when a new battle starts.
- **The website** needs only small data: match rows now; per-match viewer packs and derived
  stat tables later (~1–5 MB a battle). That goes to Cloudflare so it works from the phone too.
- The failing PC drives only ever hold a small queue (staging) of battles on their way to the share.

## Components

### 1. Helper app (`wt-helper`, Windows) — `src/wt_analytics/helper/`
Single-file exe (PyInstaller onefile, Python 3.14, built by `.github/workflows/helper.yml` on
every push to `src/`, published as the GitHub release `helper`), linked from the site. Config:
`%APPDATA%\wt-analytics\config.toml` (share path, staging path, site URL, key, my userId).
- **ingest / queue** (`ingest.py`) — one folder per battle in staging with `state.json`. Steps:
  stage client replay → copy to share → copy its live log to share → fetch server replay → copy to share → decode → copy
  decoded tables to share → write manifest → send the match row to the site → clear staging.
  Each step is recorded when done; failures (share offline, network) retry after 5 min and never
  repeat finished steps. Staging is deleted only after everything is on the share.
- **share** (`share.py`) — copy to a temp name, verify sha256, rename. Identical re-copies are
  no-ops; a different file under an existing raw name is refused.
- **server_fetch** (`server_fetch.py`) — `GET https://wt-game-replays.warthunder.com/<session>/NNNN.wrpl`
  (302 to Gaijin's CDN, no login), parts until 404/403, one at a time, each part retried 6× with
  backoff (the CDN resets connections), resumable. If part 0 isn't there yet: retry after
  2 min, 10 min, 30 min, 1 h, 3 h, 12 h, then decode from the client replay alone (at once for
  battles more than a day old: an imported backlog doesn't wait for server replays that are gone).
  `ingest` skips files that aren't replays and says so.
- **redecode** — `wt-helper redecode [session…] [--all]` (default: battles where nothing decoded)
  copies a battle's raw replays back from the share into staging (checked against the manifest's
  sha256) and runs decode → publish → manifest → summary again. Used after a decoder upgrade or a
  failed decode.
- **inbox** — replays uploaded on the website wait in R2 `inbox/`; the helper downloads them,
  queues them and deletes them from R2.
- **live_logger** (`live_logger.py`) — one thread, one keep-alive connection, a minimal HTTP
  client (httpx cost 5 % of a core at these rates; this costs 0.6 %). Battle = `/map_info.json`
  `valid: true` (in the hangar `/state` and `/indicators` are valid too); ended after 5 s without
  it. A recording cut off by a crash is closed off when the logger restarts. Polls `/state` and `/indicators` 10 Hz,
  `/map_obj.json` 5 Hz, `/hudmsg` and `/gamechat` 2 Hz (incremental ids), `/mission.json` 1 Hz,
  `/map_info.json` 1 Hz (+ `/map.img` when it changes), plus any endpoint found in the page's
  scripts at 1 Hz. Raw responses → `staging/live/<UTC start>/<endpoint>.jsonl.zst`; uploads nothing.
  The queue's `raw_live` step gives a log to the replay whose start time is within 10 min of it;
  logs no replay claims go to `raw/live/unmatched/` after a day.
- **replay_watcher** — polls the Replays folder (`[paths] replays`, else `<install>/Replays` via
  3DHeat's install finder) every 10 s between battles; a file is taken once its size is stable
  for 10 s. Replays there on the first run are history (`wt-helper ingest <folder>` imports them).
- **service** (`wt-helper run`) — logger thread + a 10 s loop: during a battle nothing else runs;
  between battles: watcher → queue, website inbox every 2 min, queue steps, unmatched live logs.
  A running decode is killed the moment a battle starts and redone later. One instance only
  (holds local port 48111). Log: `staging/logs/helper.log` (rotating).
- **install / doctor** — `install` writes the config, adds `HKCU\…\Run\wt-helper`
  (`conhost.exe --headless wt-helper.exe run`; no admin rights needed — a logon task would) and starts it; `doctor` checks the decoder, share,
  staging, Replays folder, website key, 8111 and the queue.
- Next: **install_catalogue** (English names/prices from the install) and **los** (terrain from
  the install, stays on the PC; only results go to the site).

### 2. Decoding — `src/wt_analytics/pipeline/`
- **decode** — 3DHeat-Ext-WarThunder pinned to the v0.2.2 commit (`HEAT3D_NO_UPDATE=1`). The wide
  table is split into per-event Parquet tables (positions, hits, kills, weapons, fires, logistics,
  other), sorted by track and time, dropping columns empty in that table (halves the size).
- **accel** — checked drop-in speed-ups for the pinned decoder version only.
- **battle** — decodes client and server replays in parallel processes at below-normal priority;
  merges the match summary (server replay first, client fills gaps such as country).
- **summary** — the match row for the site.

### 3. Website — `worker/` + `web/`
Cloudflare Worker (plain JS, no build step) serving `web/` and a JSON API:
- `POST /api/login`, cookie or bearer auth with one secret key (`API_KEY`).
- `PUT /api/upload` (raw client `.wrpl` → R2 inbox + a pending match row).
- `GET/DELETE /api/inbox[/<name>]` (helper), `PUT /api/matches/<session>` (helper publishes a row).
- `GET /api/matches[/<session>]`, `GET /api/health`.
Static pages hold no data; everything is under `/api/` and needs the key. Cloudflare Access can
be added in front as a second layer.

### 4. desk-hub
A Samba share only — setup in `docs/LAPTOP.md`.

## Storage layout
Share (`W:\`, `/srv/wt` on desk-hub):
```
raw/replays/client/<yyyy-mm-dd>/<session>.wrpl
raw/replays/server/<session>/0000.wrpl …
raw/live/<session>/<endpoint>.jsonl.zst …   (live logger; raw/live/unmatched/<UTC start>/ if no replay)
decoded/heat3d-0.2.2/<session>/{client,server}/{positions,hits,…}.parquet, match.json, …
decoded/heat3d-0.2.2/<session>/result.json
manifest/<session>.json                    (header info, step status, every file's sha256)
```
Cloudflare: D1 `matches` (one row per battle) and `files` (R2 objects); R2 `inbox/` (transient),
later `viewer/` and `derived/`. Everything on Cloudflare is rebuildable from the share.

## Measured (2 battles, 2026-11-21)
| | Ground | Air |
|---|---|---|
| Raw on share (client + server) | 19 MB | 36 MB |
| Decoded on share | 30 MB | 38 MB |
| On Cloudflare | one D1 row | one D1 row |
| Helper end to end (this cloud machine, 2.1 GHz Xeon) | 110 s | 80 s |

## Changes from the original spec (`docs/SPEC.md`)
- Website hosted on Cloudflare (Worker + D1 + R2) instead of `localhost`, behind a key.
- The `wt` CLI becomes `wt-helper` (a Windows exe with the same subcommands).
- The share holds per-battle manifest JSON files instead of an append-only `matches.parquet`.
