# wt-analytics

Personal post-match analytics for War Thunder, like Leetify for CS. It records every match
(air and ground), keeps the raw data forever, and shows reports and a replay viewer on a
private website.

**Status:** Phase 0 done (verified on real replays). Nothing to install yet. See [`docs/PHASE0.md`](docs/PHASE0.md)
for findings and next steps.

## How it will work
1. Open your private site (Cloudflare, login required) and download **wt-helper.exe** from
   *Downloads*. Run it once; it starts with Windows.
2. Play. The helper records the game's local API and picks up your replays. After each battle
   it uploads them, and the report appears on the site a minute or two later.
3. Old replays: drag them onto the site's *Upload* page.

Nothing is shown during a match. Everything is post-match only.

## Docs
- [`CLAUDE.md`](CLAUDE.md): project brief, rules, module map
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the pieces fit, and why
- [`docs/DATA.md`](docs/DATA.md): what each data source really contains
- [`docs/STATS.md`](docs/STATS.md): stats catalogue
- [`docs/PHASE0.md`](docs/PHASE0.md): verification status
- [`docs/SPEC.md`](docs/SPEC.md): original spec
