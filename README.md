# wt-analytics

Personal post-match analytics for War Thunder, like Leetify for CS. It records every match
(air and ground), keeps the raw data forever, and shows reports and a replay viewer on a
private website.

**Status:** Phase 1 in progress. The site is live at https://wt-analytics.lancus.workers.dev (key login),
and the helper's processing works end to end; the Windows exe, live logger and replay watcher come next.
Phase 0 findings: [`docs/PHASE0.md`](docs/PHASE0.md).

## How it will work
1. Set up the desk-hub share once ([`docs/LAPTOP.md`](docs/LAPTOP.md)) and map it as `W:` on the PC.
2. Download **wt-helper.exe** from the site's *Downloads*. Run it once; it starts with Windows.
3. Play. The helper records the game's local API and picks up your replays. After each battle it
   fetches the server replay, decodes everything at low priority, stores it on desk-hub, and the
   report appears on the site a minute or two later. Only small summary data goes to Cloudflare.
4. Old replays: drag them onto the site's *Upload* page (the PC picks them up), or
   `wt-helper ingest <folder>`.

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
