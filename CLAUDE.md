# wt-analytics — brief for every session

Personal post-match analytics for War Thunder (air and ground), like Leetify for CS.
It records everything it can about every match, keeps the raw data forever, derives stats,
and shows reports and a replay viewer on a private website.
**Principle: capture everything raw, derive later.** Every stat must be re-computable from
stored data.

Full original spec: `docs/SPEC.md`. Architecture and the reasons for it: `docs/ARCHITECTURE.md`.
Current findings and status: `docs/PHASE0.md`.

## Hard rules (non-negotiable)
1. **Post-match only.** Nothing shows enemy information while a match runs. The helper only
   records to disk and uploads **after the battle ends**. The site never shows live data.
2. **Read-only sources:** the game's local HTTP API (`127.0.0.1:8111`) and replay files the game
   saves or serves (incl. `wt-game-replays.warthunder.com`). Never read game memory, inject or
   hook. Install files are only *read* (names, economy, terrain) by the helper on the PC.
3. **Nothing from the game is redistributed.** No game assets, levels, terrain or replays in
   the repo or anywhere public. R2 bucket is private; the site sits behind Cloudflare Access.
   **Terrain/level data never leaves the PC**: LOS and heatmaps are computed by the helper and
   only their results are uploaded.
4. **Secrets** (Cloudflare/R2 tokens) live outside git (`.env`, `wrangler secret`, the helper's
   config in `%APPDATA%`). Never commit them.
5. **No SQLite/DuckDB files on network shares.** Databases live locally or in D1.

## Architecture (website-first)
```
Gaming PC (Windows)                     Cloudflare (private, behind Access)
┌─────────────────────────┐   HTTPS    ┌───────────────────────────────────────┐
│ helper app (wt-helper)  │ ─────────► │ Worker: API, uploads, auth, serves web │
│  live_logger  (8111)    │  upload    │ R2: raw/, decoded/, derived/, viewer/  │
│  replay_watcher         │  after     │ D1: manifest + summary tables          │
│  queue (upload/retry)   │  battle    │ Container: Python pipeline             │
│  install_catalogue      │            │   decode (3DHeat, pinned) → derive     │
│  los (terrain, local)   │ ◄───────── │   server_replay_fetch                  │
└─────────────────────────┘  jobs      │ web/: dashboard + 2D/3D viewer         │
                                       └───────────────────────────────────────┘
```
- The helper is a single Windows `.exe` (built by GitHub Actions), downloadable from the site.
- Manual upload of `.wrpl` / server-replay zips through the site's Upload page also works.
- The laptop/Samba share is **optional** (backup mirror only); the main storage is R2.

## Module map
| Path | What |
|---|---|
| `src/wt_analytics/common/schema.py` | decoder pin, `SCHEMA_VERSION`, decoded table layout |
| `src/wt_analytics/helper/` | PC app (Phase 1, next): `live_logger`, `replay_watcher`, `queue`, `install_catalogue`, `los`, `doctor` |
| `src/wt_analytics/pipeline/` | cloud container: `service` (HTTP job API), `decode` (3DHeat + per-event split), `summary` (D1 match row), `accel` (checked speed-ups for the pinned decoder) |
| `Dockerfile.pipeline` | the container image (Python 3.14; built by `wrangler deploy`) |
| `worker/` | Cloudflare Worker, plain JS ES modules: `index.js` (API, auth, upload, queue consumer), `jobs.js` (server-replay fetch, decode orchestration), `pipeline.js` (container Durable Object), `replay.js` (wrpl header), `util.js`; `schema.sql` (D1), `wrangler.jsonc` |
| `web/` | static site served by the Worker. Now: a plain Phase 1 working page; designed UI from Phase 2 |
| `tools/docker-proxy.sh` | docker wrapper for builds behind a TLS proxy (`WRANGLER_DOCKER_BIN`) |
| `web/design/` | **the design system** (tokens.css, components.css) — created in Phase 2, then used everywhere |
| `tools/` | one-off scripts (e.g. `dump-8111.ps1`) |
| `docs/` | SPEC, ARCHITECTURE, DATA (verified facts), STATS (catalogue), PHASE0 |

## Data layout (R2 bucket `wt-analytics`, private)
```
raw/replays/client/<yyyy-mm-dd>/<session>.wrpl
raw/replays/server/<session>/0000.wrpl ...
raw/live/<session>/<endpoint>.jsonl.zst
raw/maps/<map>/<version>/map.img, map_info.json
catalogue/<game_version>/names.json, economy.json, ranges.json   (small, from the PC install)
decoded/<decoder>-<version>/<session>/*.parquet
derived/<schema_version>/<table>/...parquet
los/<los_version>/<session>/...                                     (computed on the PC)
viewer/<pack_version>/<session>.bin                                 (compact viewer pack)
```
Decoded per source: `decoded/heat3d-0.2.2/<session>/{client,server}/{positions,hits,kills,weapons,fires,logistics,other}.parquet`
+ `match.json`, `messages/objectives/flight.parquet`, and `<session>/result.json`.
D1 (`worker/schema.sql`): `matches` (one row per battle + status of every step) and `files`
(every R2 object with size and sha256). Everything in D1 is rebuildable from R2.

## Coding standards
- Python 3.12+, `uv`, wheel-only deps. Type hints everywhere, dataclasses/pydantic where useful.
- Vectorised data work (polars/DuckDB/numpy/pyarrow). No Python loops over rows.
- Small focused functions, no copy-pasted logic, no dead code, no speculative stubs.
- JS: ES modules, no frameworks, no build step, no globals. Viewer uses Canvas2D/WebGL only.
- Idempotent pipeline: re-runs never duplicate; every step records status in the manifest.
- Decoder versions pinned (`HEAT3D_NO_UPDATE=1`); every output records decoder + version.
- `schema_version` on derived data; bumping it re-derives everything.

## Performance budgets
- Helper while playing: negligible CPU (<1 % of one core), no work during a battle except logging.
- Decode + derive a typical match: ≤ ~1 min.
- Dashboard pages: < 1 s. Viewer: load a match < 2 s, steady 60 fps for 16v16 with all overlays
  (4K, RTX 2060, Chrome). Heavy work in the pipeline/helper or Web Workers, never the main thread.

## Testing rules (keep token cost low)
- Test only non-trivial logic likely to break: death/defence classifiers, LOS/heatmap maths,
  coordinate alignment, queue/retry/idempotency, decoder integration.
- Tests come from the spec and real data, never from pasting current output.
- Run only tests for code you changed. No tests for getters, config, formatting, UI layout.
- Real replays are local fixtures only (`tests/fixtures/`, git-ignored).

## UI
Use the frontend-design approach and the `dataviz` skill before any chart. Dark tactical
instrument look; colour only where it means something. Visual review loop (Playwright
screenshots → fresh Sonnet reviewer) for every UI piece — see `docs/SPEC.md` §6b.

## How to work
- This main session owns architecture and code. Sonnet subagents only for bounded research,
  docs, visual reviews and fresh-eyes code reviews.
- **After any big change, update every affected file in the same commit**: this file,
  `README.md`, `docs/ARCHITECTURE.md`, `docs/DATA.md`, `docs/STATS.md`, `docs/PHASE0.md`.
- Small, meaningful commits. Branch: `claude/tender-brahmagupta-cdjah0`.

## Status
Phase 0 done (`docs/PHASE0.md`, facts in `docs/DATA.md`).
Phase 1 in progress:
- Cloud side built and **verified end to end locally** (`wrangler dev` + Docker): upload → server
  replay fetch (10 parts) → decode in container → R2 + D1 summary, ~2.5 min per ground battle.
- R2 bucket, D1 db (`326cea19-…`) and queues `wt-jobs`/`wt-jobs-dlq` created on the account.
- **Not deployed yet**: the account's API token lacks the Containers permission (user to add).
- Next: deploy, then the helper exe (logger, watcher, upload queue, install catalogue).
- Server replays are the primary source; client replays add my instruments + session id.
- Me = userId `110703665` (server replays have no author).
- Real fixtures (git-ignored): `tests/fixtures/client/*.wrpl`, `tests/fixtures/server/<sid>/`.
