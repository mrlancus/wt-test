> **Note (2026-11-21):** the original spec, kept as written. The architecture has since moved to a
> website-first design (Cloudflare Worker + R2 + Container, plus a downloadable PC helper).
> Where this file and `docs/ARCHITECTURE.md` disagree, ARCHITECTURE.md wins.

# Build: War Thunder personal analytics ("wt-analytics")

**Repo:** `mrlancus/wt-test` on GitHub (already created, empty). Build everything there.

You are building a personal, post-match analytics system for my War Thunder games – think Leetify for CS, but for War Thunder. It records everything it possibly can about every match I play (air and ground), stores it permanently, derives a huge set of stats, and shows me detailed reports: where I die, why, what I missed, what I do well, and how I'm trending.

The guiding principle: **capture everything raw, derive later.** Storage is cheap; data I didn't record is gone forever. Every stat must be re-computable from stored data, so I can add new stats in future and re-run them over all past matches.

Read this whole document before writing code. Work in the phases at the end, and stop for my review where it says so.

---

## 1. Hard rules (non-negotiable)

1. **Post-match only.** Nothing may show enemy information to me while a match is running – no overlays, no live map, no live enemy distances, no alerts. The live logger only *records* to disk. Reports appear after the match ends. This is what keeps it fair and within Gaijin's rules.
2. **Read-only sources only:** the game's official local HTTP API (`http://127.0.0.1:8111`) and replay files the game itself saves or serves. Never read game memory, inject anything, hook the client, or touch files inside the game install except reading data the converter needs from my own install.
3. **Nothing from the game is redistributed.** No game assets, level files or replays go into the repo or anywhere public. R2 is private.
4. **Secrets** (R2 keys etc.) live in a local `.env` / config outside git. Add `.gitignore` entries.
5. **Never put SQLite (or DuckDB) databases on the network share** – file locking over SMB corrupts them. Databases live on the PC; the share holds files only.

---

## 2. My setup (design around this)

**Gaming PC (Windows 11)** – does all the work
- i5-9400F, RTX 2060, 32 GB RAM.
- **Both local drives are failing:** C: is a 240 GB WD Green SSD at ~44 % health; D: is a 1 TB Seagate HDD with pending/uncorrectable sectors. Treat both as disposable. Keep only a small staging/queue folder locally (configurable path, default on D:), move finished files to the share as soon as possible, and make the local index fully rebuildable from the share. A new PC is coming soon, so installation must be easy to redo (one command).
- Python is fine (I'd rather avoid anything needing manual compilation). Use Python 3.12+, `pip`/`uv`, pure-Python or wheel-available deps only.

**Desk laptop ("desk-hub" laptop)** – storage only
- Ubuntu Server 26.04, **4 GB RAM**, always on, lots of disk. It already runs a kiosk desk screen, Klipper/Moonraker/Crowsnest for my 3D printer, and other agents. **Do not run heavy work on it** – Klipper must never be starved of RAM or CPU mid-print.
- Its only job here: a **Samba share** the PC writes to (mapped as a drive letter on Windows, e.g. `W:`). Provide the exact Samba setup commands/config for the laptop (one share, one user, LAN only, no guest access) and the Windows mapping steps.
- Do not modify the desk-hub project itself.

**Cloudflare R2** – small extracted data only
- I already have a Cloudflare Workers Paid plan and use R2 elsewhere. Cloudflare Workers are available if something genuinely needs them (e.g. viewing reports from my phone outside home), but don't add a Worker unless there's a clear reason – the default is everything local.
- Upload **derived/summary data** (per-match summaries, per-life and per-death records, per-event aggregate tables, trend tables) – the small stuff, as an offsite backup and so it's reachable from anywhere. Raw replays and full decoded tables stay on the laptop.
- Use the S3-compatible API from Python (e.g. `boto3`) with credentials from config. Make what goes to R2 configurable, and keep it well under ~1 GB/month by default.

---

## 3. Data sources

### 3a. Live logger – localhost:8111 (runs on the PC during matches)
- Detect when a battle starts and ends (e.g. `/indicators` → `valid`, `/map_info.json` → `valid`, mission status). Create one session per battle with a unique id and wall-clock timestamps.
- Discover endpoints by reading the page and its JS at `http://127.0.0.1:8111/` – don't trust my list. At least: `/state`, `/indicators`, `/map_obj.json`, `/map_info.json`, `/mission.json`, `/hudmsg?lastEvt=N&lastDmg=N`, `/gamechat?lastId=N`, `/map.img`.
- Poll at configurable rates (defaults: `/state` + `/indicators` 10 Hz, `/map_obj.json` 5 Hz, `/hudmsg` + `/gamechat` 2 Hz with incremental ids, `/mission.json` 1 Hz, `/map_info.json` and `/map.img` once per battle and on change).
- **Store every raw response** with a high-resolution timestamp as zstd-compressed JSONL, one file per session per endpoint (or one multiplexed file – your call, document it). Never drop fields, even ones we don't understand yet.
- Robust: tiny CPU use, short timeouts, survives the game closing/opening, never crashes on bad JSON, autostarts at log-in (Windows Task Scheduler or Startup), logs its own errors.
- Note: `map_obj.json` only contains what my minimap shows (spotted enemies, teammates, objectives). That's fine – it's still valuable ("was the killer ever spotted before he killed me?").

### 3b. Replays (the main data source)
- **Client replays:** the game's `Replays` folder (need "save replays" enabled – tell me where to turn it on). Watch it and ingest new `.wrpl` files once they are complete (size stable / file unlocked).
- **Server replays (preferred – they contain every player's position and view direction):** these are multi-part (`0000.wrpl`, `0001.wrpl`, …) and downloadable per session id. Research how existing tools get them (wrpl-inspector can download a server replay from a session id; the forum shows URLs of the form `https://wt-game-replays.warthunder.com/<session_hex>/0000.wrpl`) and how I can get my session ids (client replay header, battle messages, etc.). Automate fetching the server replay for every match I play, with polite rate limiting and retries. If full automation isn't possible, make it a one-click/one-command step and tell me exactly why.
- Keep **every raw replay file forever** on the share, named by session id, with a manifest (game version, replay format version, map, mode, date, my vehicle(s), file hashes, sizes).

### 3c. Decoding
- Primary decoder: **3DHeat-Ext-WarThunder** (`github.com/Holdi601/3DHeat-Ext-WarThunder`, Python, MIT). It converts `.wrpl` (client or server zip) into Parquet/JSON with ~105 columns: positions and attitude, turret/gun angles, view yaw/pitch (all players' tanks in server replays), kills, deaths, hits with hit location/outcome/shell, shots, launches, impacts, fires, rewards, repairs/rearms/reloads, despawns, aircraft flight data for the recording player, economy, scoreboard, players and units. It can also build terrain heightmaps/objects from my own install for line-of-sight work.
- Also evaluate **wrpl-inspector** (Go, AGPL) and **LivingTheDagor/WrplReplayParser** (C++/Python) as fallbacks or cross-checks, and record which decoder + version produced each output.
- **Pin decoder versions.** Every major game update can change the replay format. When decoding fails, keep the raw file, mark the match "pending re-decode", alert me in the report, and support a `redecode --all/--since/--version` command for when the parser is updated.
- Verify things yourself on a real replay before relying on them (e.g. sample rates, what's actually present in client vs server replays, coordinate systems, units, how my player is identified). Document findings in `docs/DATA.md`.

---

## 4. Storage layout

On the share (laptop), something like:
```
wt/
  raw/replays/client/<date>/<session>.wrpl
  raw/replays/server/<session>/0000.wrpl ...
  raw/live/<session>/*.jsonl.zst
  raw/maps/<map_name>/map.img, map_info.json      (once per map/version)
  decoded/<decoder>-<version>/<session>/*.parquet  (full tables, zstd)
  derived/<schema_version>/<table>/...parquet      (rebuildable)
  manifest/matches.parquet                         (append-only, also rebuildable)
  terrain/<map>/...                                (from my install, local only, never uploaded)
```
- Parquet with zstd, split into tables by event type (positions, shots, hits, kills, damage, launches, economy, players, units …), sorted by unit + time, so columns aren't mostly empty.
- Local on the PC: a staging/queue folder and a DuckDB (or SQLite) index for fast queries, fully rebuildable from the share. If the share is offline, queue locally and sync later. Never lose data on a failed copy (write to temp, verify hash, then move).
- Track a `schema_version` for derived data; bumping it re-derives everything.
- Show storage use per category in the dashboard and warn when the laptop disk gets low.

R2 (small): `derived/` summaries and per-life/per-death tables, plus the manifest. Configurable.

---

## 5. Stats – record and derive everything

Compute per **match**, per **life/spawn**, per **death**, per **vehicle**, per **map**, per **mode/BR bracket**, per **nation**, and **over time** (rolling trends, last N matches vs previous N). Every stat should be filterable by those dimensions. The list below is a minimum – add anything else the data allows, and keep a `docs/STATS.md` catalogue of every stat with its definition, unit and source columns.

### General / match
- Map, mode (AB/RB/SB, air/ground, event modes like Nuclear Escalation), BR, uptier/downtier, nation, team sizes, my lineup, game version, duration, result, my placement on the scoreboard, team kill split.
- Economy: SL, RP, per action and per minute, with/without premium/boosters (whatever the data or rewards breakdown provides), repair cost, net SL. Base kills vs air kills vs ground targets (I've seen e.g. 1 air kill ≈ 8,160 SL / 664 RP vs 2 bases ≈ 12,347 SL / 2,376 RP – compute these ratios automatically per vehicle/BR).
- Time alive, time spent active, spawns, SP, assists, captures.

### Ground
- **Deaths (the most important table):** time, position, map grid, elevation, killer (name, vehicle, nation), weapon/shell, hit location and module chain, distance, killer's bearing relative to my hull and turret, was I moving (speed), **time since I last stopped**, time since my last shot, time since I last changed position, was I on an open-ground/exposed area vs near cover (use terrain/objects if available), was the killer **ever on my minimap** before the kill (from the live log), **was the killer inside my camera/view cone** in the last 5/10/30/60 s (from view yaw/pitch + FOV), how long the killer had been **aiming at me** (his gun/view direction toward me), whether there was **line of sight** between us earlier that I failed to use (terrain heightmap, if feasible), CAS/air deaths, artillery, team-kills, first-shot vs return-fire deaths.
- **Duels:** every engagement between me and an enemy (first sighting → shots → outcome). Who saw whom first, who fired first, my reaction time (enemy enters my view cone → my first shot at him), first-shot win rate, hit rate, time to kill.
- **Spotting:** enemies that were inside my view cone and line of sight but I never shot at; average detection distance; time-to-spot by map and range; how often I die to never-seen enemies.
- **Shooting:** shots fired, hits, penetrations, non-pens, ricochets, kills per shot, accuracy by range band, by target vehicle, by ammo type, hit-location heatmap on target silhouettes, shots wasted on dead/burning targets, reload behaviour, ATGM launches and outcomes (incl. APS intercepts if present).
- **Movement & positioning:** distance driven, % time moving vs stationary, average speed, time exposed after firing, peeks and re-peeks from the same spot, routes taken per map, heatmaps of where I sit / where I die / where I kill, elevation advantage at kill/death time, hull-down estimates if possible, time near cover.
- Damage taken: from where, what modules, crew losses, fires, repairs, time spent repairing.
- Vehicle-specific: e.g. BMPT-72 cannon vs ATGM usage and results, Ka-50 Vikhr launches, ranges and survival.

### Air
- **Deaths:** killer, weapon (exact missile type), launch range, launch altitudes (mine and his), aspect at launch, my speed/altitude/heading during the missile's flight, **what I did to defend** (turned cold / notched / cranked / climbed / dived – classify from my heading relative to the missile and the shooter over time), notch quality (angle off the missile's velocity, time held), chaff/flares used and when, multipath altitude, terrain masking, time from his lock/launch to impact if present, whether I fired back, whether I was in a furball.
- **Missiles I fire:** type (R-77, R-77-1, R-27ER/ET, R-73 …), range, both altitudes, closure, aspect, target's reaction, flight time, outcome (hit, notched, flared, kinematic miss, target out-turned it, lost lock), Pk tables by missile × range band × altitude band × aspect × target-defending-or-not. Lock mode used (TWS / STT / IRST) if available.
- **Missiles fired at me:** same breakdown from the defender's side – which defences actually work for me, at what ranges.
- Flight: altitude/speed/energy over time, G, AoA, fuel, throttle (my aircraft only), time at low altitude, time supersonic, energy state at merge, turn rates achieved.
- Base bombing / ground targets in air RB: bases destroyed, time to first base, survival after base runs, reward per run.
- Radar/RWR data if any of it exists in the sources.

### Trends & insights
- Rolling averages and improvement curves for the key stats above.
- "Top 5 things costing you the most deaths this week" – generated from the data (e.g. "62 % of your ground deaths happened within 4 s of moving into a new position", "you're notching R-77-sized threats correctly but turning back hot within 15 s").
- Per-map pages: my best/worst spots, enemy sniper positions that killed me, common routes.
- Personal bests and streaks.

---

## 6. Reports & dashboard (on the PC)

- A local dashboard served from the PC (static HTML/JS + a tiny local server that reads the DuckDB index/Parquet). Plain HTML/CSS/JS, no heavy frameworks, dark theme, fast.
- **Post-match report** opens (or notifies me) shortly after each match: summary, economy, a timeline, and one card per death with a map overlay (my track, the killer's track, view cones, sight lines, the moment he became visible) and the classified "what went wrong".
- Match list with filters, per-vehicle and per-map pages, trends, the stats catalogue, data health (decode failures, storage use, pending re-decodes).
- The interactive replay viewer (section 6a) – the centrepiece.
- Export any table to CSV.

## 6a. Interactive replay viewer – "WT replays, but better"

The goal: open any match and see what really happened and what could have been done – every unit, every threat, every sight line – far beyond what the in-game replay shows. Build **2D first** (top-down, fast to build, the main daily tool), then **3D** (terrain view) once 2D is solid. Both share one data/time model.

**Core**
- Free timeline scrubbing, play/pause, speed control (0.25×–16×), frame stepping, keyboard shortcuts. Jump-to markers on the timeline for every kill, death, hit, launch, capture and base kill.
- All units from both teams, no fog of war, with smooth interpolated motion (the replay samples at ~10–15 Hz server-side; never show jitter). Unit icons by type, team colours, name and vehicle labels that stay readable and don't overlap.
- Tracks/trails with adjustable length, toggles per team/unit/type, click a unit to follow it and see its stats panel at that moment.
- Ground units: hull direction, turret direction, gun direction, **view cone** (from view yaw/pitch). Air units: altitude (labels and colour), heading, speed, missiles in flight with their full paths, chaff/flares, launches and impacts.
- Shots and hits drawn as lines with outcome (pen, non-pen, ricochet, kill), hit location on click.

**The "better than WT" layer**
- **Line of sight:** lines between units that actually had LOS at that moment, computed against the terrain heightmap and map objects (forests, towns) that 3DHeat builds from my install. Precompute LOS per match after decoding (not in the browser at view time) at a sensible time step, and cache it.
- **Threat overlay ("who could see me"):** for the selected unit (default: me), highlight every enemy with LOS to it, distinguishing "could see me" vs "was looking/aiming at me", with how long they'd been aiming.
- **Danger heatmap:** at the current time, shade the map by how many known enemies had LOS to each cell (and how many were facing it). This answers "where could I have gone instead" – a covered route vs the open field I drove across. Precompute on a grid; keep it fast.
- **Death playback:** from any death card in the report, jump to 30 s before the death with the killer highlighted, his view cone shown, the moment he first had LOS on me marked, and my own view cone (did I ever look at him?).
- **History overlay:** my deaths/kills across all matches on this map as a toggleable layer.
- **Air:** 3D-aware view of missile engagements – my heading relative to the missile over time, notch/cold/crank classification shown on the timeline, launch ranges, terrain masking moments.
- Be honest in the UI about approximations: LOS ignores small bushes and destroyed buildings; label it as approximate.

**Map base:** the game's map image (`/map.img`) and grid from `map_info.json` for 2D, aligned exactly to replay coordinates (verify alignment on several maps). 3D uses the terrain heightmap/objects from my own install (local only, never uploaded or committed).

**Performance budgets (hard requirements)**
- 2D viewer: a steady **60 fps** while playing a full 16v16 ground match with all overlays on, on my machine (i5-9400F, RTX 2060, 4K 60 Hz monitor) in Chrome. Use Canvas2D or WebGL (PixiJS or raw WebGL are fine) – **no per-frame DOM/SVG for units**. Draw only what changed or what's visible; batch draws; cache static layers (map, heatmap) to offscreen canvases.
- 3D viewer: three.js (or similar), instanced meshes, terrain LOD, 60 fps target at 1440p internal resolution, gracefully lower quality settings if needed.
- Load a match into the viewer in **under 2 s** from the local index. Ship the viewer a compact precomputed binary/columnar format per match (e.g. typed arrays / Arrow / Parquet via a small reader) – not giant JSON.
- Heavy work (LOS, heatmaps, interpolation tables) happens in the pipeline or in Web Workers – never blocking the main thread.
- Measure it: include a small FPS/frame-time overlay (toggle) and check the budgets before calling a phase done.

## 6b. Look and feel – it must look genuinely good

This matters as much as the data. If it looks like a generic AI dashboard, it has failed.
- Use the **frontend-design skill** (and any other relevant skills you have) before designing the UI, and set a clear visual direction first: a dark, modern, tactical/military-instrument feel – clean, information-dense but calm, sharp typography, a restrained colour palette where colour means something (team, threat level, outcome), consistent spacing.
- Define a small design system up front (colour tokens, type scale, spacing, components: cards, tables, timeline, tooltips, toggles) in one place, and use it everywhere. No one-off styles.
- Charts: use the **dataviz skill** before making any chart. Consistent chart styling across the app, readable at a glance.
- Smooth, purposeful animation (timeline, panel transitions) – never janky, never decorative for its own sake.
- Show me screenshots/previews of the UI direction early (before building every page) so I can steer it.
- **Avoid the default "AI look".** No generic purple/blue gradients, no glassmorphism everywhere, no oversized rounded cards with emoji icons, no centred hero sections, no random drop shadows, no rainbow charts, no filler stat tiles, no Inter-on-grey sameness. Apply real design principles: clear visual hierarchy, alignment to a grid, consistent spacing rhythm, deliberate contrast, limited type sizes and weights, colour only where it carries meaning, density appropriate for an analysis tool, and good empty/loading/error states.

### Visual review loop (mandatory)
Every UI piece – each page, the map viewer, overlays, charts, the report cards – goes through a review loop before it counts as done:
1. Render it with real data in headless Chromium (Playwright) at my sizes – 3840×2160 (4K) and 2560×1440 – plus a phone width for the report pages, and capture screenshots. For the viewer, also capture several moments of a busy match (furball, many units, all overlays on) and a short frame-time recording.
2. Send the screenshots to a **separate Sonnet reviewer subagent** that did not build it. Give it the design system, the principles above and this checklist, and ask for a strict verdict (pass/fail per item plus concrete fixes), not praise:
   - Does it look like a polished, purpose-built tool, or like a generic AI dashboard?
   - Hierarchy: is the most important thing obvious at a glance?
   - Spacing, alignment and grid consistency; typography scale and weights; contrast and legibility at 4K.
   - Colour use: meaningful, consistent with the tokens, readable for both teams and threat levels, colour-blind-safe.
   - **Map/viewer specific:** map image sharp and correctly aligned to units (no offset at the edges); unit icons clear and distinguishable at all zoom levels; labels readable and not overlapping; trails, view cones, LOS lines and the danger heatmap readable together without turning into visual noise; overlays layered sensibly; the selected unit and threats immediately obvious; timeline markers clear.
   - Charts follow the dataviz rules.
   - Empty, loading and error states look intentional.
3. If anything fails, **redo that part** (not just a cosmetic patch – rework the layout or rendering if that's the real problem), re-screenshot, and review again with a fresh reviewer. Repeat until it passes. If it still fails after 4 rounds, stop and show me the screenshots and the reviewer's notes so I can decide.
4. Keep the final screenshots in `docs/screenshots/` so I can see progress, and show me the key ones at the end of each phase.

Run the same loop for performance on the viewer: measure frame times; if it misses the budget, profile and fix before moving on.

- Plain HTML/CSS/JS (ES modules) by default. If you think a small library is worth it for the viewer (PixiJS, three.js, a tiny chart lib), justify it in one line. No heavy frameworks or build steps unless there's a strong reason – I'd rather have no compile step.

---

## 7. Engineering

- One Python project/repo `wt-analytics` with clear modules: `live_logger`, `replay_watcher`, `server_replay_fetch`, `decode`, `derive`, `storage` (share + R2 sync + queue), `index`, `dashboard`, `cli`.
- A single CLI: `wt install`, `wt run` (background service: logger + watchers + pipeline), `wt ingest <file|dir>`, `wt fetch-server <session>`, `wt redecode`, `wt rederive`, `wt sync`, `wt report <session>`, `wt dashboard`, `wt doctor` (checks 8111, share, R2, disk space, replay setting, decoder versions).
- One config file (paths, rates, share path, R2 bucket/keys, what to upload, retention).
- Idempotent pipeline: re-running never duplicates; every step records status per match in the manifest.
- Low footprint while I play: the logger must be negligible; decoding/derivation runs after the battle ends, at low process priority, and pauses if a new battle starts.
- **Code quality:** this has to be genuinely well-engineered, not "AI-generated and slow". Clear module boundaries, small focused functions, typed Python (type hints, dataclasses/pydantic where useful), vectorised data work (pandas/polars/DuckDB/numpy – never Python loops over millions of rows), no copy-pasted logic, no dead code, meaningful names, short docstrings where intent isn't obvious. Same standard for the JS: modules, no globals soup, no frameworks-for-the-sake-of-it.
- **Performance everywhere:** decoding + derivation of a typical match should finish within ~1 minute on my PC; dashboard pages render in well under a second; queries go through DuckDB over Parquet, not loading everything into memory. Profile the slow paths once they exist and fix them.
- **Testing – only where it earns its place.** I care a lot about token cost, and you tend to over-test. Rules:
  - Write tests only for logic that is non-trivial and likely to break: the death/defence classifiers, LOS/heatmap maths, coordinate alignment, the storage queue/retry and idempotency, and the decoder integration.
  - **Base tests on the spec and on real data, not on whatever the code currently outputs.** A test must check the behaviour we actually want (e.g. "in this real match I died while moving across an open field 3 s after a stop" or "a target at exactly 90° to the missile velocity is classed as notching"), so it can catch a wrong implementation. Never write a test by running the code and pasting its output in as the expected value.
  - Don't add or re-run tests for code that hasn't changed. Run only the tests relevant to what you touched.
  - No tests for trivial getters, config loading, formatting or UI layout.
  - Use a couple of my real replays as fixtures (kept locally, never committed).
- Logging to a rotating log file on the share (and a small local fallback).
- Docs: `README.md` (setup in as few steps as possible), `docs/DATA.md` (what each source really contains, verified), `docs/STATS.md` (catalogue), `docs/LAPTOP.md` (Samba setup).

---

## 7a. How you should work

- **First, create a proper `CLAUDE.md`** in the repo root (and keep it up to date): project purpose, the hard rules from section 1, architecture overview, module map, data layout, coding standards, performance budgets, design-system location, testing rules, how to run things, and current status. Keep it concise and accurate – it's the brief for every future session. Add nested `CLAUDE.md` files in big subfolders (e.g. `viewer/`, `pipeline/`) only if they genuinely help.
- **One main session owns the architecture and code** (this session, Opus). Keep the design coherent – one style, one set of helpers, one data model.
- **Use Sonnet subagents for bounded, self-contained jobs** that return a short report: researching a format or API, cataloguing columns/endpoints from a real file, writing setup docs, the **visual review loop** in section 6b (a fresh reviewer each round, for every page and the map viewer), and a **fresh-eyes code review** of each finished phase for bugs and performance. Reviewers never review their own work. Don't split core implementation across subagents.
- **Use skills where they apply:** frontend-design for UI direction, dataviz before any chart, and any others listed to you that fit a task. Check what's available rather than guessing.
- Plan before big pieces (architecture, viewer rendering, LOS/heatmap approach): write a short design note in `docs/`, then build.
- Commit in small, meaningful steps with clear messages. Keep `README.md`, `CLAUDE.md` and the docs current as you go – not at the end.
- When something in this spec turns out to be wrong or impossible on real data, say so plainly and propose the best alternative instead of faking it.

## 8. Phases

**Phase 0 – Verify (stop and report to me before building more)**
0. Create `CLAUDE.md` and the repo skeleton.
1. Inspect the 8111 API on my machine (or document how I can dump it) and list every endpoint and field.
2. Install 3DHeat, decode one client replay and one server replay of mine, and report: what's actually there, sample rates, how to identify me, view-direction coverage, hit/shot detail, coordinates/units, anything missing vs this spec.
3. Work out how to get server replays for my matches automatically.
4. Check that the map image aligns with replay coordinates, and that 3DHeat's terrain/objects export works for LOS.
5. Propose any changes to the plan based on what you found.

**Phase 1 – Capture & store:** Samba share on the laptop, live logger, replay watcher, server replay fetch, decode, storage layout, manifest, queue/retry, R2 sync of the small stuff, `wt doctor`. Autostart.

**Phase 2 – Core stats + UI foundation:** per-match, per-life and per-death tables for ground and air, economy, the death classification. Set the visual direction and design system (show me previews first), then build the post-match report and match list on it.

**Phase 3 – 2D viewer:** the full 2D replay viewer from section 6a with LOS, threat overlay, danger heatmap and death playback, meeting the performance budgets.

**Phase 4 – Deep stats:** duels, spotting/view-cone analysis, missile Pk and defence analysis, movement/exposure, heatmaps, trends and the auto-generated "top things costing you deaths", wired into the dashboard and viewer.

**Phase 5 – 3D viewer and polish:** the 3D terrain viewer, per-map pages, history overlays, exports.

At the end of each phase: run a Sonnet fresh-eyes review (bugs, performance, UI quality), fix what matters, check the performance budgets, then give me a short summary of what works, what's verified on real data, and what's next.
