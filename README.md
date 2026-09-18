# hltv-demos

Download CS2 GOTV demos (`.dem`) from HLTV by event and map, and install them
into your CS2 `game/csgo` directory — ready for `playdemo`.

## Features

- Finds the HLTV event page from a name/slug via site search
- Only downloads demos of maps that were **actually played** (listed-but-vetoed maps are skipped)
- Cloudflare-safe downloads (`curl_cffi` Chrome impersonation; plain requests/curl get 403)
- Resumable: interrupted downloads continue with HTTP Range (`.part` files)
- Dedup via a local manifest — repeat calls skip already-downloaded archives
- Map names in **English or Chinese** (荒漠迷城=Mirage, 炼狱小镇=Inferno, 核子危机=Nuke, 炙热沙城II=Dust2, 远古遗迹=Ancient, 阿努比斯=Anubis, ...)
- Auto-discovers CS2 in Steam libraries (`/mnt/*`), or set `HLTV_DEMOS_CSGO_DIR`

## Install

Requires Python 3.10+.

```bash
pip install .
hltv_demos --help
```

## Usage

```bash
# plan only (shows matches, played maps, demo sizes)
hltv_demos --event blast-open-porto-2026 --maps Mirage,Inferno --dry-run

# latest 3 matches on Inferno, extract demos into the CS2 dir
hltv_demos --event blast-open-porto-2026 --maps 炼狱小镇 --latest 3

# all matching matches, all maps
hltv_demos --event major-championship --maps ""
```

It prints `playdemo` commands for each extracted demo, e.g.:

```
playdemo "/mnt/.../game/csgo/blast-open-porto-2026-team1-team2-mirage.dem"
```

## Python API

```python
from hltv_demos import run
result = asyncio.run(run(event="blast-open-porto-2026", maps="炼狱小镇", latest=3))
```

## Notes

- `latest=0` means all matching matches; archives are deleted after extraction unless `--keep-rars`
- No HLTV login needed as of 2025-09; if HLTV starts requiring login the tool fails with a clear message
- `7zz` is auto-downloaded to the tools folder if missing
- Downloads large archives one by one; prefer `--dry-run` first for big events
