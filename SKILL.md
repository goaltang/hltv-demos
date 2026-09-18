---
name: hltv-demos
description: Download CS2 GOTV demos (.dem) from HLTV into the game/csgo folder, filtered by event and map, with Cloudflare bypass, resume, dedup and Chinese map-name support (荒漠迷城/炼狱小镇/核子危机...). Use when the user asks to download HLTV 比赛 demo/录像/replay, add demos of a specific map (Mirage/Inferno/Nuke/...), or query which matches of an event were played on a map.
---

# HLTV Demos

Fetch CS2 match demos from HLTV and install them into the CS2 `game/csgo` directory.

## Quick use (Python kernel)

    await hltv_demos(event="blast-open-porto-2026", maps="炼狱小镇", latest=3)
    await hltv_demos(event="blast-open-porto-2026", maps="Mirage,Inferno", dry_run=True)

Shell form (same args): `hltv_demos --event ... --maps ... --latest 3 --dry-run`

## What run() does

1. Finds the HLTV event page from a slug/name (site search).
2. Lists the event results, fetches each candidate match page and detects which
   maps were actually PLAYED (mapholder `div.results.played` — listed-but-vetoed
   maps are skipped; this is the step most likely to be wrong without it).
3. Resolves the demo archive URL (`/download/demo/<id>` 302 → r2-demos.hltv.org).
   No HLTV login needed as of 2025-09; if HLTV starts requiring login the skill
   fails with a clear message instead of silently returning nothing.
4. Downloads (curl_cffi `impersonate="chrome"` — requests/cloudscraper get 403;
   plain curl gets 403 even on the final R2 URL), with `.part` Range resume and
   byte-size validation. Interrupted calls: just call again, it continues.
5. Extracts only the wanted maps' `.dem` files into the CS2 dir and returns
   ready `playdemo` commands.

## Notes

- `maps` accepts English or Chinese names (荒漠迷城=Mirage, 炼狱小镇=Inferno,
  核子危机=Nuke, 炙热沙城II=Dust2, 远古遗迹=Ancient, 阿努比斯=Anubis, ...),
  comma-separated.
- `latest=0` means all matching matches; `keep_rars=False` deletes archives
  after extraction (adopted foreign-name archives are never deleted).
- CS2 dir is auto-discovered (Steam libraries on /mnt/*); override with
  `csgo_dir=...` or env `HLTV_DEMOS_CSGO_DIR`.
- A manifest at `~/tools/hltv-demos/manifest.json` remembers downloaded
  archives and extracted maps so repeat calls skip re-downloading.
- Downloads run inline in the calling cell; for big batches prefer `dry_run`
  first, then call per map. `7zz` is auto-downloaded to `~/tools/hltv-demos/`
  if missing.
