---
name: hltv-demos
description: Plan, download, validate, and install CS2 GOTV demos from HLTV by event and map. Supports English and Chinese map names, played-map filtering, safe resume, archive validation, and manifest deduplication. Use when the user asks for HLTV match demos, replays, GOTV files, or demos from a specific CS2 event or map.
compatibility: Linux x86-64 or Windows WSL2, Python 3.10+, outbound HTTPS, writable CS2 game/csgo directory
license: MIT
---

# HLTV Demos

Use the bundled CLI to install CS2 demos. This skill writes outside the workspace
and can download large archives. Always show a dry-run plan and get user approval
before a real run.

## First use

From the directory containing this `SKILL.md`:

```bash
./scripts/install --agent auto
./scripts/doctor
```

The installer creates an isolated environment under
`~/.local/share/hltv-demos/` and can link this skill into detected Agent skill
directories. It installs Python dependencies. On first extraction, the tool may
download the official Linux x86-64 `7zz`; its SHA-256 is pinned and verified
before execution. Tell the user about these changes before running the installer.

## Required workflow

1. Prefer an exact HLTV event URL. An exact name or slug also works.
2. Run a dry plan and show the result to the user:

```bash
./scripts/hltv-demos --event 'https://www.hltv.org/events/1234/event-slug'   --maps 'Mirage,Inferno' --latest 3 --dry-run
```

3. Confirm the event, matches, estimated size, archive directory, CS2 directory,
   and archive-retention policy with the user.
4. Only after approval, repeat with `--yes` and without `--dry-run`:

```bash
./scripts/hltv-demos --event 'https://www.hltv.org/events/1234/event-slug'   --maps 'Mirage,Inferno' --latest 3 --yes
```

Use `--json` when structured output is useful. Progress and diagnostics go to
stderr, leaving stdout as one JSON document.

## Important behavior

- Empty `maps` means every `.dem` in each selected archive. A real event-wide
  request with empty maps and `latest=0` is refused.
- Archives are kept by default. Use `--no-keep-rars` only when the user asks.
- `--csgo-dir` accepts either the CS2 root or the final `game/csgo` directory.
- `--download-dir` selects archive storage; the default is `~/Downloads`.
- Chinese aliases include 荒漠迷城=Mirage, 炼狱小镇=Inferno,
  核子危机=Nuke, 炙热沙城II=Dust2, 远古遗迹=Ancient, and 阿努比斯=Anubis.
- Ambiguous event searches fail and return candidates. Never guess one.
- Unknown archive sizes fail by default. Do not use `--allow-unknown-size`
  without explaining the risk and getting explicit approval.
- Existing conflicting demos are preserved. Failed downloads retain `.part`
  files for resume. Archives are deleted only after validated extraction.

## Troubleshooting

Run `./scripts/doctor`. Do not attempt a real download until its FAIL items are
fixed. This release does not auto-support native Windows, macOS, Linux ARM, or
restricted sandboxes without outbound network and external-directory access.
