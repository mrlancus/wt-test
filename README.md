# wt-analytics

Personal post-match analytics for War Thunder, like Leetify for CS. It records every match
(air and ground), keeps the raw data forever, and shows reports and a replay viewer on a
private website.

**Status:** Phase 1 in progress. The site is live at https://wt-analytics.lancus.workers.dev (key login),
and the helper is complete: live 8111 logger, replay watcher, queue, server fetch, decoding, autostart.
The Windows exe is built by GitHub Actions. Left in Phase 1: a test on the real PC, then the Phase 1 review.
Phase 0 findings: [`docs/PHASE0.md`](docs/PHASE0.md).

## How it will work
1. Set up the desk-hub share once ([`docs/LAPTOP.md`](docs/LAPTOP.md)) and map it as `W:` on the PC.
2. Download **wt-helper.exe** from the site's *Download* section and run once, in a Command Prompt:
   `cmdkey /add:deskhub.local /user:wtshare /pass` (saves the share password), then
   `wt-helper.exe install --share \\deskhub.local\wt --key <site key> --user-id <your userId>`, then `wt-helper.exe doctor`.
   It then starts hidden at every logon (`wt-helper.exe uninstall` stops that).
3. Play (with "save replays" on in the game). During a battle the helper only records the game's
   local API (< 1 % CPU). After it, it takes your replay, fetches the server replay, decodes at low
   priority (stopped at once if a new battle starts), stores everything on desk-hub, and the match
   appears on the site a minute or two later. Only small summary data goes to Cloudflare.
   Its log: `<staging>\logs\helper.log`.
4. Old replays: drag them onto the site's *Upload* page (the PC picks them up), or
   `wt-helper ingest <folder>`. `wt-helper redecode` decodes stored battles again from desk-hub.

Nothing is shown during a match. Everything is post-match only.

## Deploying the website
Needs Node 22+ and `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` (Workers Scripts, R2, D1 edit).
```bash
cd worker && npm install
npx wrangler d1 execute wt-analytics --remote --file schema.sql
npx wrangler secret put API_KEY
npm run deploy
```

## Docs
- [`CLAUDE.md`](CLAUDE.md): project brief, rules, module map
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the pieces fit, and why
- [`docs/DATA.md`](docs/DATA.md): what each data source really contains
- [`docs/STATS.md`](docs/STATS.md): stats catalogue
- [`docs/LAPTOP.md`](docs/LAPTOP.md): desk-hub Samba share setup
- [`docs/PHASE0.md`](docs/PHASE0.md): verification status
- [`docs/SPEC.md`](docs/SPEC.md): original spec
