# wt-analytics

Personal post-match analytics for War Thunder, like Leetify for CS. It records every match
(air and ground), keeps the raw data forever, and shows reports and a replay viewer on a
private website.

**Status:** Phase 1 in progress. The cloud pipeline (upload → server replay → decode → storage) works
end to end in local testing; deployment waits for a Containers permission on the Cloudflare token.
Phase 0 findings: [`docs/PHASE0.md`](docs/PHASE0.md).

## How it will work
1. Open your private site (Cloudflare, login required) and download **wt-helper.exe** from
   *Downloads*. Run it once; it starts with Windows.
2. Play. The helper records the game's local API and picks up your replays. After each battle
   it uploads them, and the report appears on the site a minute or two later.
3. Old replays: drag them onto the site's *Upload* page.

Nothing is shown during a match. Everything is post-match only.

## Deploying the cloud side
Needs Node 22+, Docker, and `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` with Workers Scripts,
R2, D1, Queues and **Containers** edit permissions.
```bash
cd worker && npm install
npx wrangler d1 execute wt-analytics --remote --file schema.sql
npx wrangler secret put API_KEY
npm run deploy
```
Behind a TLS-inspecting proxy, deploy with `WRANGLER_DOCKER_BIN=../tools/docker-proxy.sh npm run deploy`.

## Docs
- [`CLAUDE.md`](CLAUDE.md): project brief, rules, module map
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the pieces fit, and why
- [`docs/DATA.md`](docs/DATA.md): what each data source really contains
- [`docs/STATS.md`](docs/STATS.md): stats catalogue
- [`docs/PHASE0.md`](docs/PHASE0.md): verification status
- [`docs/SPEC.md`](docs/SPEC.md): original spec
