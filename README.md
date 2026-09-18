# hltv-demos

Download CS2 GOTV demos (`.dem`) from HLTV by event and map, then install them
into the CS2 `game/csgo` directory, ready for `playdemo`.

## Features

- Finds an HLTV event from its name or slug.
- Downloads only maps that were **actually played**, not vetoed maps.
- Uses `curl_cffi` Chrome impersonation for Cloudflare-protected downloads.
- Resumes interrupted downloads with validated HTTP Range responses.
- Uses a manifest to skip requested demos that are already installed.
- Supports English and Chinese map names.
- Extracts to a temporary directory, validates output, then installs atomically.
- Tests archive integrity before extraction or optional deletion.

## Install

Requires Python 3.10+.

```bash
pip install .
hltv_demos --help
```

## Usage

```bash
# Plan only. This does not require a local CS2 installation.
hltv_demos --event blast-open-porto-2026 --maps Mirage,Inferno --dry-run

# Extract Inferno from the latest three matching matches.
hltv_demos --event blast-open-porto-2026 --maps 炼狱小镇 --latest 3

# Extract every .dem from the latest three matches.
hltv_demos --event blast-open-porto-2026 --latest 3

# Delete each archive only after all requested demos pass validation.
hltv_demos --event blast-open-porto-2026 --maps Mirage --no-keep-rars
```

The JSON result includes ready commands such as:

```text
playdemo "match-name-mirage"
```

## Python API

```python
import asyncio
from hltv_demos import run

result = asyncio.run(run(
    event="blast-open-porto-2026",
    maps="炼狱小镇",
    latest=3,
))
```

`run()` moves blocking HTTP, file and 7-Zip work to a worker thread, so awaiting
it does not block the caller's event loop.

## Safety and behavior

- `latest=0` means all matching matches.
- Empty `maps` means all `.dem` members in each selected archive. A real run
  with both empty `maps` and `latest=0` is refused to prevent an accidental
  event-wide download. `dry_run=True` is always allowed.
- Archives are kept by default. Pass `--no-keep-rars` or
  `keep_rars=False` to delete them after successful validation and extraction.
- An existing demo with an unexpected size is preserved and reported as a
  conflict. It is never silently overwritten.
- Archive reuse is tied to the same HLTV demo ID. Unrelated archives are never
  adopted merely because their byte sizes match.
- `csgo_dir` and `HLTV_DEMOS_CSGO_DIR` specify the
  `Counter-Strike Global Offensive` root. The tool appends `game/csgo`.
- The download directory can be overridden with `HLTV_DEMOS_DL_DIR`.
- The manifest is stored at `~/tools/hltv-demos/manifest.json`.
- `7zz` is downloaded into `~/tools/hltv-demos/` if it is unavailable.

## Tests

```bash
uv run python -m unittest discover -v
```
