# Phase 0 — verification status

| # | Step | Status |
|---|---|---|
| 0 | `CLAUDE.md` + repo skeleton | done |
| 1 | Inspect the 8111 API | deferred to the helper (Phase 1); not needed to start |
| 2 | Decode client + server replays | **done** on 1 air + 1 ground battle — see `DATA.md` |
| 3 | Get server replays automatically | **done**: works with no login; needs retry logic for the CDN |
| 4 | Map alignment; terrain for LOS | deferred: map image comes from 8111 (helper), terrain needs the install (helper) |
| 5 | Plan changes | below |

## Key findings
1. **Server replays are the main source.** They cover the whole battle, every tank at ~24 Hz
   with turret and view direction, full missile paths, and hit outcomes. Client replays stop
   when you leave and have only ~3 Hz for other tanks with no view data.
2. **Automatic fetch works.** Session id from the client replay header → plain HTTPS download
   from Gaijin's CDN, no login. Parts until 404. The CDN resets connections now and then,
   so every part needs retries.
3. **"How long was he aiming at me" is measurable.** On your ground death, the killer's view
   was on you (< 1°) for 3.5 s before the shot at 520 m.
4. **Your cockpit instruments are only in the client replay** (air). Keep both replays.
5. **Missed tank rounds are probably not recorded.** `shot` rows are hits. Ground accuracy
   (hits / rounds fired) may need the 8111 log (ammo count over time) — to check in Phase 1.
6. **Names and prices need your install.** Without it the decoder only sees ids; the helper
   runs on the PC, so it can read them there.
7. **Decoding is slow-ish:** a ground server replay took 105 s on a 4-vCPU cloud machine.
   Profile in Phase 1; acceptable for a background job anyway.

## Changes to the plan
(Later superseded on storage: replays stay on desk-hub, the PC decodes, Cloudflare holds only
website data — see `ARCHITECTURE.md`.)
- Server replay fetch is required, not optional; keep client replays too.
- Ground accuracy: derive rounds fired from the 8111 ammo/indicator log if the replay lacks it.
- 8111 inspection and map alignment move into Phase 1 (helper) instead of a separate dump.
- Decode time budget: aim for < 60 s after profiling; the pipeline is async so the report may
  take ~2 min after a battle.

## Next
Phase 1 is under way: see the Status section of `CLAUDE.md`.
