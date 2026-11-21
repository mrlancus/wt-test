# Phase 0 — verification status

| # | Step | Status |
|---|---|---|
| 0 | `CLAUDE.md` + repo skeleton | done |
| 1 | Inspect the 8111 API | **needs you**: run `tools/dump-8111.ps1` in a battle |
| 2 | Decode one client + one server replay, report contents | **needs you**: upload replays |
| 3 | Get server replays automatically | worked out (below), to confirm on your session ids |
| 4 | Map image alignment; terrain export for LOS | **needs you**: 8111 dump (map image) + replay of the same match |
| 5 | Plan changes | done: website-first, see `ARCHITECTURE.md` |

## What I need from you
1. **Turn on replay saving:** in the game, *Options → Main parameters* (General), tick
   **"Save replays"** / **"Autosave replays of battles"**. Replays then land in
   `<War Thunder folder>\Replays\` (Steam: `C:\Program Files (x86)\Steam\steamapps\common\War Thunder\Replays`).
2. Play **one ground battle** with `tools/dump-8111.ps1` running during it
   (`powershell -ExecutionPolicy Bypass -File dump-8111.ps1 -Seconds 120`).
   Ideally do one air battle too.
3. Upload to this session: the zip(s) from your Desktop and the `.wrpl` file(s) of those battles.
   I'll download the server replay myself from the session id.

## Server replays — how (step 3)
- Session id: u64 at byte 732 of any client `.wrpl` header, written as 16-digit hex.
- URL: `https://wt-game-replays.warthunder.com/<hex>/0000.wrpl`, then `0001`, … until 404/403.
  No login needed (wrpl-inspector does exactly this).
- Plan: the helper reads the id the moment the client replay is written and sends it to the
  API. The cloud retries the fetch with backoff (5 min, 15 min, 1 h, 3 h, 12 h) and downloads
  one part at a time.
- **To confirm on your data:** how soon replays appear, and whether every random battle has
  one. If some don't, those matches just keep the client replay (less data on other players'
  view direction).
- **Fallback without client replays:** the session id isn't known to be available from 8111.
  So "save replays" must be on for automatic fetching.

## Proposed changes to the plan
1. **Website-first** (approved): helper exe + Cloudflare Worker/R2/D1/Container. Laptop optional.
2. **Decode in the cloud** with 3DHeat (pure Python, works on Linux). The helper uploads a
   small names/economy catalogue built from your install so the cloud output has English
   names and prices.
3. **LOS on the PC**: terrain extraction needs the game's Oodle DLL and must stay local anyway.
4. Cross-check decoder: **wrpl-inspector** (Go, AGPL) reads the same format. We'd use it only as
   an external cross-check tool, never vendored, to keep licences clean.
   **WrplReplayParser** (C++) needs compiling and supports one replay version; skip it.
