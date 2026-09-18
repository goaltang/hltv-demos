# hltv-demos

Safe HLTV GOTV demo planning, download, validation, and CS2 installation.

[简体中文说明](README.zh-CN.md)

## Supported platforms

Version 0.3 supports **Linux x86-64** and **Windows WSL2** with Python 3.10+.
Native Windows, macOS, and Linux ARM are not yet auto-supported. A manually
installed `7z`/`7zz` on `PATH` may work on other platforms, but CS2 discovery
and those environments are not tested.

The tool needs outbound HTTPS access and write access to the CS2 `game/csgo`
directory. It stores state under `~/tools/hltv-demos` and archives in
`~/Downloads` unless overridden.

## Install for an Agent

Clone the repository, then run:

```bash
git clone https://github.com/goaltang/hltv-demos.git
cd hltv-demos
./scripts/install --agent auto
./scripts/doctor
```

Select an Agent explicitly when auto-detection is not suitable:

```bash
./scripts/install --agent claude
./scripts/install --agent codex --agent cursor
./scripts/install --agent all
```

Supported user skill roots:

| Agent | Skill root |
|---|---|
| Prime Agent | `~/.prime/agent/skills/` |
| Claude Code | `~/.claude/skills/` |
| OpenAI Codex | `~/.agents/skills/` |
| Cursor | `~/.cursor/skills/` |
| Gemini CLI | `~/.gemini/skills/` |

Agent Skills support varies by client version. For a repository-scoped install,
link this repository as `hltv-demos` under the client’s project skill directory,
such as `.agents/skills`, `.claude/skills`, `.cursor/skills`, or
`.github/skills` where supported.

The installer creates versioned isolated runtimes under
`~/.local/share/hltv-demos/releases/` and atomically switches a `current`
link. It never replaces an unrelated existing skill path.

## Safe quick start

First inspect the plan. This does not require a working CS2 installation and
does not download an archive:

```bash
./scripts/hltv-demos   --event 'https://www.hltv.org/events/1234/event-slug'   --maps Mirage,Inferno --latest 3 --dry-run
```

After checking the exact event, matches, sizes, and paths:

```bash
./scripts/hltv-demos   --event 'https://www.hltv.org/events/1234/event-slug'   --maps Mirage,Inferno --latest 3 --yes
```

A real CLI run requires `--yes`. Archives are retained by default. Use
`--no-keep-rars` only if you want validated archives removed after extraction.

Use `--json` for machine-readable output. stdout remains valid JSON; progress
is sent to stderr.

## Diagnostics

```bash
./scripts/doctor
./scripts/doctor --json
```

`--csgo-dir` accepts either the `Counter-Strike Global Offensive` root or the
final `game/csgo` directory. Use `--download-dir` to select archive storage.

## Python API

```python
import asyncio
from hltv_demos import run

result = asyncio.run(run(
    event="https://www.hltv.org/events/1234/event-slug",
    maps="炼狱小镇",
    latest=3,
    dry_run=True,
))
```

The Prime Agent runtime may wrap the module as a directly callable skill. Other
Python environments must call `hltv_demos.run(...)` as shown above.

## Security and recovery

- The official Linux x86-64 7-Zip archive has a pinned SHA-256 and is verified
  before its executable is installed.
- Resumed HTTP responses validate `Content-Range` and final byte length.
- Archives pass `7zz t` before extraction.
- Members are extracted into a temporary directory, validated, and atomically
  installed. Unsafe paths and conflicting existing demos are rejected.
- Unknown archive sizes are refused unless `--allow-unknown-size` is explicitly
  supplied.
- Disk space is checked before archive download and demo extraction.
- The manifest skips already verified demos. Failed downloads retain `.part`
  files for a later resume.

## Development

```bash
uv sync
uv run python -m unittest discover -v
uv build
```

Normal tests use mocked HTTP and do not download HLTV archives.

## License

[MIT](LICENSE)
