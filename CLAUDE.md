# wt-analytics — brief for every session

Personal post-match analytics for War Thunder (air and ground), like Leetify for CS.
It records everything it can about every match, keeps the raw data forever, derives stats,
and shows reports and a replay viewer on a private website.
**Principle: capture everything raw, derive later.** Every stat must be re-computable from
stored data.

Full original spec: `docs/SPEC.md`. Architecture and the reasons for it: `docs/ARCHITECTURE.md`.
Verified data facts: `docs/DATA.md`. desk-hub Samba setup: `docs/LAPTOP.md`.

## Hard rules (non-negotiable)
1. **Post-match only.** Nothing shows enemy information while a match runs. The helper only
   records to disk and uploads **after the battle ends**. The site never shows live data.
2. **Read-only sources:** the game's local HTTP API (`127.0.0.1:8111`) and replay files the game
   saves or serves (incl. `wt-game-replays.warthunder.com`). Never read game memory, inject or
   hook. Install files are only *read* (names, economy, terrain) by the helper on the PC.
3. **Nothing from the game is redistributed.** No game assets, levels, terrain or replays in
   the repo or anywhere public. **Replays and full decoded tables stay at home** (desk-hub share);
   Cloudflare gets only what the website needs (match rows, later viewer packs and derived
   tables), plus website uploads held in a private inbox until the PC takes them.
   **Terrain/level data never leaves the PC**: LOS and heatmaps are computed by the helper and
   only their results are uploaded.
4. **Secrets** (Cloudflare/R2 tokens) live outside git (`.env`, `wrangler secret`, the helper's
   config in `%APPDATA%`). Never commit them.
5. **No SQLite/DuckDB files on network shares.** Databases live locally or in D1.

## Architecture: desk-hub stores, the PC works, Cloudflare shows
```
Gaming PC: wt-helper ──SMB──► desk-hub Samba share W:\  (raw replays, decoded tables, manifests)
  capture, server-replay fetch,
  decode (low priority), queue ──HTTPS──► Cloudflare Worker + D1 (+ R2 inbox / viewer packs)
                               ◄──────── website uploads (R2 inbox, deleted once taken)
```
- The helper is a single Windows `.exe` (built by GitHub Actions), downloadable from the site.
- desk-hub only serves files (Klipper runs there: no processing on it).
- Site: https://wt-analytics.lancus.workers.dev (key login). Details: `docs/ARCHITECTURE.md`.

## Module map
| Path | What |
|---|---|
| `src/wt_analytics/common/` | `schema.py` (decoder pin, `SCHEMA_VERSION`, decoded table layout), `config.py` (the TOML config) |
| `src/wt_analytics/helper/` | PC app: `cli` (`wt-helper ingest/process`), `ingest` (staging queue + steps), `share` (verified copies), `server_fetch`, `api` (site client). Next: `live_logger`, `replay_watcher`, `install_catalogue`, `los`, `doctor` |
| `src/wt_analytics/pipeline/` | decoding on the PC: `battle` (client+server in parallel, low priority), `decode` (3DHeat + per-event split), `summary` (match row), `accel` (checked speed-ups for the pinned decoder) |
| `worker/` | Cloudflare Worker, plain JS ES modules: `index.js` (API, auth, upload inbox, match rows), `replay.js` (wrpl header), `util.js`; `schema.sql` (D1), `wrangler.jsonc` |
| `web/` | static site served by the Worker. Now: a plain Phase 1 working page; designed UI from Phase 2 |
| `web/design/` | **the design system** (tokens.css, components.css) — created in Phase 2, then used everywhere |
| `tools/` | one-off scripts (e.g. `dump-8111.ps1`) |
| `docs/` | SPEC, ARCHITECTURE, DATA (verified facts), STATS (catalogue), PHASE0 |

## Data layout
desk-hub share (`W:\`):
```
raw/replays/client/<yyyy-mm-dd>/<session>.wrpl
raw/replays/server/<session>/0000.wrpl ...
raw/live/<session>/<endpoint>.jsonl.zst                       (live logger, next)
decoded/heat3d-0.2.2/<session>/{client,server}/{positions,hits,kills,weapons,fires,logistics,other}.parquet
                                + match.json, messages/objectives/flight.parquet; <session>/result.json
manifest/<session>.json                                         (step status + sha256 of every file)
```
Cloudflare: D1 (`worker/schema.sql`) `matches` (one row per battle) and `files` (R2 objects);
R2 `inbox/` (website uploads, transient), later `viewer/` and `derived/`. All rebuildable from the share.
PC staging (`D:\wt-staging`): one folder per battle in progress (`state.json`), cleared when done.

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
  `README.md`, `docs/ARCHITECTURE.md`, `docs/DATA.md`, `docs/STATS.md`, `docs/LAPTOP.md`.
- Small, meaningful commits. Branch: `claude/tender-brahmagupta-cdjah0`.

## Status
Phase 0 done (`docs/PHASE0.md`, facts in `docs/DATA.md`).
Phase 1 in progress:
- Site **deployed** (Worker + D1 `wt-analytics` + R2 `wt-analytics`). Verified end to end on the live
  site with both real battles: website upload → inbox → helper → server fetch → decode → share
  (a local stand-in here) → match row on the site. Helper: ~80 s air, ~110 s ground.
- Done in the helper: `ingest`/`process` commands, queue, share copies, server fetch, inbox.
- Next: live logger (8111), replay watcher + `run` service + autostart, install catalogue,
  `doctor`, the Windows exe build (GitHub Actions) and Downloads page; then Phase 1 review.
- Server replays are the primary source; client replays add my instruments + session id.
- Me = userId `110703665` (server replays have no author).
- Real fixtures (git-ignored): `tests/fixtures/client/*.wrpl`, `tests/fixtures/server/<sid>/`.
