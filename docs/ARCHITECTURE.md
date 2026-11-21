# Architecture

Decided 2026-11-21: **website-first**. Everything you look at is a private website on your
Cloudflare account. The capture half runs in a small helper app on the gaming PC, which you
download from that website. Old replays can also be dragged onto the site's Upload page.

## Why not a pure website
A website cannot record the 8111 data while you play, cannot watch the `Replays` folder by
itself, cannot read your game install, and Chrome restricts public sites calling `127.0.0.1`.
So a helper app is unavoidable for capture. Everything else (processing, storage,
viewing) lives in the cloud, which also takes the failing PC drives out of the picture.

## Components

### 1. Helper app (`wt-helper.exe`, Windows)
Single-file exe built by GitHub Actions (PyInstaller) from `src/wt_analytics/helper/`.
Installed once from the site's Downloads page; registers itself to start at log-in.
- **live_logger** – polls 8111 at the configured rates and writes raw responses as
  zstd JSONL into a local staging folder. Uploads only after the battle ends (rule 1).
- **replay_watcher** – watches the game's `Replays` folder; once a `.wrpl` is complete
  (size stable, file unlocked), queues it for upload. Reads the session id from the header
  (u64 at offset 732) and tells the API, so the cloud can fetch the server replay.
- **queue** – local, small, durable upload queue (atomic files + a tiny SQLite on the local
  disk). Hash-verified uploads, retry with backoff, deletes local copies only after the
  server confirms the hash. Survives offline periods.
- **install_catalogue** – reads, from your own install, the small tables the decoder needs
  for names/economy/ranges and uploads them as JSON per game version (no assets, no levels).
- **los** – the only heavy local job, run at low priority after decoding finishes and paused
  if a battle starts: downloads the match's compact positions, computes line of sight and
  danger grids against the terrain extracted from your install, uploads only the results.
  Terrain stays on the PC (rule 3).
- **doctor** – checks 8111, the replay setting, the Replays folder, connection to the API,
  free disk space, versions.

The helper never runs analysis during a battle and stays below ~1 % CPU while logging.

### 2. Cloudflare Worker (`worker/`)
Plain JS ES modules, no build step, deployed with `wrangler`.
- Serves `web/` (static assets) and a JSON API.
- **Auth:** the site is behind Cloudflare Access (only your account); the helper uses an
  Access service token.
- **Uploads:** R2 multipart upload for large replays (bypasses request-size limits).
- On upload or session-id notification, enqueues a pipeline job (Cloudflare Queues) and
  schedules server-replay fetch.
- Answers dashboard queries from D1 (small summary tables) and streams Parquet/viewer packs
  from R2.

### 3. Pipeline container (`src/wt_analytics/pipeline/`, Cloudflare Containers)
A Python 3.12 container image started on demand by the Worker.
- **server_replay_fetch** – `GET https://wt-game-replays.warthunder.com/<session_hex>/NNNN.wrpl`
  for NNNN = 0000, 0001, … until 404/403. No auth needed. Polite: one request at a time,
  backoff and retries over several hours, since the replay appears some time after the battle.
- **decode** – 3DHeat-Ext-WarThunder at a pinned version (`HEAT3D_NO_UPDATE=1`), pure Python,
  runs on Linux; uses the uploaded install catalogue for names/economy. Output split into
  per-event Parquet tables under `decoded/<decoder>-<version>/<session>/`.
  On failure: raw kept, manifest status `pending_redecode`, shown on the Data Health page.
- **derive** – DuckDB/polars over the decoded tables → `derived/<schema_version>/…` plus rows
  for the D1 summary tables.
- **viewer_pack** – compact typed-array binary per match for the viewer.

### 4. Web app (`web/`)
Plain HTML/CSS/JS ES modules. Design system in `web/design/`. Dashboard, post-match reports,
match list, per-vehicle/per-map pages, trends, stats catalogue, data health, uploads,
downloads, and the 2D (later 3D) replay viewer (Canvas2D/WebGL, Web Workers).

### 5. Optional backup
The laptop Samba share becomes an optional mirror (`wt sync --to-share`), not required.
A second copy of R2 can also be made with rclone from the laptop at low priority.

## Data flow for one match
1. Battle starts → helper logs 8111 locally.
2. Battle ends → helper uploads the live log; the game saves the client replay → helper
   uploads it and the session id.
3. Worker records the match in D1 and enqueues: fetch server replay, decode, derive, pack.
4. Helper sees "decoded" → computes LOS locally → uploads results → Worker marks the match
   complete; the site notifies (browser notification / helper tray toast) that the report is
   ready.

## Storage and cost estimate
| Item | Size per match (estimate, to verify in Phase 0) |
|---|---|
| Client replay | 2–20 MB |
| Server replay (all parts) | 10–60 MB |
| 8111 live log (zstd) | 1–5 MB |
| Decoded + derived + viewer pack | 5–20 MB |

At ~10 matches/day: roughly 5–30 GB/month in R2, about $0.10–0.45/month added each month
(R2 storage $0.015/GB-month, no egress fees). Containers bill by active CPU/memory time,
a few minutes per match. D1 and Workers fit in the Paid plan's included usage.

## Changes from the original spec (`docs/SPEC.md`)
- Main storage is the private R2 bucket, not the laptop share (user approved 2026-11-21).
- Processing runs in a Cloudflare Container instead of on the PC; the PC only logs, uploads
  and computes LOS.
- Dashboard is hosted (behind Access) instead of `localhost`; reachable from the phone.
- The `wt` CLI becomes the helper app (`wt-helper`, with the same subcommands for power use)
  plus Worker endpoints; `wt install` = download and run the exe.
- Index is D1 (+ DuckDB inside the container) instead of a local DuckDB file.
