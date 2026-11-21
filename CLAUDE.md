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
| `src/wt_analytics/common/` | config, logging, ids, shared schema constants |
| `src/wt_analytics/helper/` | PC app: `live_logger`, `replay_watcher`, `queue`, `install_catalogue`, `los`, `doctor`, `cli` |
| `src/wt_analytics/pipeline/` | cloud container: `decode`, `derive`, `server_replay_fetch`, `manifest`, `viewer_pack` |
| `worker/` | Cloudflare Worker (plain JS ES modules, no build step) + `wrangler.toml` |
| `web/` | static site: dashboard, reports, viewer (plain HTML/CSS/JS ES modules) |
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
D1 holds the manifest (per-match status of every pipeline step) and small summary tables
for fast lists/filters. Everything in D1 is rebuildable from R2.

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
Phase 0 done (see `docs/PHASE0.md`, facts in `docs/DATA.md`). No pipeline code yet; packages
are empty on purpose. Next: Phase 1, Cloudflare side first, waiting for the user's OK.
- Server replays are the primary source; client replays add my instruments + session id.
- Me = userId `110703665` (server replays have no author).
- Real fixtures (git-ignored): `tests/fixtures/client/*.wrpl`, `tests/fixtures/server/<sid>/`.
