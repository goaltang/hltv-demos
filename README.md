# hltv-demos

Safe HLTV GOTV demo planning, download, validation, and CS2 installation.

[简体中文说明](README.zh-CN.md)

## Supported platforms

Version 0.3.1 supports **Linux x86-64** and **Windows WSL2** with Python 3.10+.
Native Windows, macOS, and Linux ARM are not yet auto-supported. The tool needs
outbound HTTPS and write access to the CS2 `game/csgo` directory.

## Install for an Agent

```bash
git clone https://github.com/goaltang/hltv-demos.git
cd hltv-demos
./scripts/install --agent auto
./scripts/doctor
```

Select one or more Agents explicitly when needed:

```bash
./scripts/install --agent qoder
./scripts/install --agent trae
./scripts/install --agent claude --agent cursor
./scripts/install --agent all
```

| Agent | User skill root |
|---|---|
| Prime Agent | `~/.prime/agent/skills/` |
| Claude Code | `~/.claude/skills/` |
| OpenAI Codex | `~/.agents/skills/` |
| Cursor | `~/.cursor/skills/` |
| Gemini CLI | `~/.gemini/skills/` |
| Qoder | `~/.qoder/skills/` |
| TRAE / TraeCode | `~/.trae/skills/` |

TRAE also discovers the shared `~/.agents/skills/` convention. `--agent trae`
uses its native root; an existing shared/Codex installation can also be reused.
For repository-scoped installation, clients may support `.agents/skills`,
`.claude/skills`, `.cursor/skills`, `.qoder/skills`, `.trae/skills`, or
`.github/skills` depending on the product and version.

The installer creates versioned runtimes under
`~/.local/share/hltv-demos/releases/` and atomically switches `current`. It
keeps the previous release for rollback and never replaces an unrelated skill.
A WSL installation belongs to that Linux distribution, not native Windows.

## Safe quick start

First inspect the plan. This does not download an archive:

```bash
./scripts/hltv-demos   --event 'https://www.hltv.org/events/1234/event-slug'   --maps Mirage,Inferno --latest 3 --dry-run
```

After checking the event, matches, sizes, archive directory, and CS2 directory:

```bash
./scripts/hltv-demos   --event 'https://www.hltv.org/events/1234/event-slug'   --maps Mirage,Inferno --latest 3 --yes
```

A real CLI run requires `--yes`. Archives are retained by default. Use
`--no-keep-rars` only when verified archives should be removed. `--json` keeps
stdout machine-readable while progress goes to stderr.

## WorkBuddy through MCP

WorkBuddy uses its own `skill.yml` format rather than the open `SKILL.md`
layout. This repository therefore supplies a local stdio MCP adapter.

Install the optional MCP dependencies inside WSL2, then generate a configuration snippet:

```bash
./scripts/install --with-mcp --agent auto
./scripts/workbuddy-mcp-config > workbuddy-hltv-mcp.json
```

Merge the resulting `mcpServers.hltv-demos` entry into WorkBuddy's
`~/.workbuddy/mcp.json`. On WSL2 the generated command uses `wsl.exe` with a
fixed distro and executable path. Keep WorkBuddy in its default/manual approval
mode; do not grant Full Access.

The MCP server exposes exactly three tools:

- `check_environment`: local, read-only diagnostics.
- `plan_download`: resolves and freezes an exact plan.
- `execute_approved_plan`: writes files only with a fresh one-use approval
  token from that plan.

The token expires after 10 minutes and prevents argument substitution or replay.
It does not replace WorkBuddy's interactive permission prompt. The execution
uses the exact demo IDs, URLs, sizes, destinations, and retention policy shown
in the approved plan; it does not rediscover matches.

Ordinary 豆包 desktop/web chat has no documented import path for arbitrary
`SKILL.md` files or local MCP configuration. For ByteDance tooling, use
**TRAE/TraeCode** or run the desired model inside another compatible Agent host.

## Diagnostics and paths

```bash
./scripts/doctor
./scripts/doctor --json
```

`--csgo-dir` accepts either the CS2 root or the final `game/csgo` directory.
`--download-dir` selects archive storage. Defaults are `~/Downloads` for
archives and `~/tools/hltv-demos` for the manifest and verified `7zz`.

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

Outside Prime Agent, call `hltv_demos.run(...)`; the installed module itself is
not a normal Python callable.

## Security and recovery

- The Linux x86-64 7-Zip archive has a pinned SHA-256.
- Demo redirects and final responses are restricted to the trusted HLTV R2
  host; archive names and destination containment are validated.
- Resumed responses validate `Content-Range` and final byte length.
- Archives pass `7zz t`; selected members are extracted into a temporary
  directory, size-checked, and atomically installed.
- Unknown archive sizes are refused by default, and disk space is checked.
- Existing conflicting demos are preserved; failed downloads retain `.part`.
- Manifest entries skip verified demos without adopting unrelated same-size
  archives.

## Development

```bash
uv sync --extra mcp
uv run python -m unittest discover -v
uv build
```

Normal tests use mocked HTTP and never download an HLTV demo archive.

## License

[MIT](LICENSE)
