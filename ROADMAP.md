# Roadmap

[简体中文](ROADMAP.zh-CN.md)

This roadmap describes intended development directions for `hltv-demos`. It is
not a promise of dates. Priorities may change when HLTV, CS2, Steam, or supported
Agent products change their interfaces.

## Current baseline — v0.3.1

The current release provides:

- Event and played-map discovery from HLTV.
- English and Chinese map aliases.
- Dry-run planning with exact archive sizes when available.
- Resumable downloads with response and final-size validation.
- Trusted HLTV demo-host and archive-name validation.
- Temporary extraction, archive integrity tests, and atomic demo installation.
- Manifest-based deduplication and existing-file conflict protection.
- Linux x86-64 and Windows WSL2 support.
- Agent installation for Prime Agent, Claude Code, Codex, Cursor, Gemini CLI,
  Qoder, and TRAE/TraeCode.
- An optional permission-aware WorkBuddy stdio MCP adapter.
- Human-readable and JSON CLI output, diagnostics, CI, and versioned release
  assets from GitHub Releases.

## Development principles

Every release should preserve these rules:

1. A plan is shown before a destructive operation.
2. Ambiguous events fail closed instead of selecting a result silently.
3. Existing demos and unrelated archives are not overwritten or deleted.
4. Agent integrations keep host permission prompts enabled.
5. Downloads remain resumable, bounded, and independently verifiable.
6. New platforms are only marked supported after an end-to-end test.
7. Normal automated tests do not download large HLTV archives.

## v0.3.2 — Reliability and real-client validation

**Goal:** close the remaining validation gaps before adding another platform.

Planned work:

- Run documented end-to-end tests for download, archive validation, extraction,
  manifest deduplication, replay command generation, and safe archive removal.
- Validate Skill discovery and execution in real Qoder and TRAE sessions.
- Validate WorkBuddy MCP setup, tool annotations, approval prompts, WSL launch,
  token expiry, and single-use execution in the real desktop client.
- Add cross-process locking and atomic merge behavior for the manifest.
- Add recorded HLTV HTML fixtures for event search, pagination, match pages,
  played-map detection, and demo redirects.
- Improve network retry classification, backoff, cancellation, and error advice.
- Add installer tests for upgrades, rollback, interruption, foreign-path refusal,
  slow networks, and optional MCP installation.
- Add `verify` diagnostics for archives, installed demos, and manifest entries.

Completion criteria:

- At least one full real download succeeds from plan through `playdemo` output.
- A repeated run downloads no duplicate data.
- Concurrent processes cannot corrupt or lose manifest state.
- Qoder, TRAE, and WorkBuddy procedures are reproduced from clean installs.
- HLTV fixture tests cover all selectors used by the downloader.

## v0.4.0 — Native Windows support

**Goal:** remove WSL as a requirement for most CS2 players.

Planned work:

- Support native Windows Python and `7zz.exe` with verified downloads.
- Parse Steam `libraryfolders.vdf` and discover CS2 across Steam libraries.
- Handle drive letters, UNC paths, spaces, Chinese paths, and long paths.
- Add a PowerShell installer and native Agent skill-directory setup.
- Add Windows download, free-space, atomic replacement, and process-locking
  implementations.
- Provide safe migration from an existing WSL installation.
- Test on supported Windows versions with Steam and CS2 installed.

Completion criteria:

- A new Windows user can install, diagnose, plan, download, and play a demo
  without WSL or manual path conversion.
- Windows CI covers unit and installer tests.
- Windows is not advertised as supported until a real CS2 installation passes
  the end-to-end checklist.

## v0.5.0 — Beginner workflow and demo management

**Goal:** make common tasks understandable without reading technical options.

Planned work:

- Add an interactive `wizard` for event, map, match count, destination, size,
  retention, and final confirmation.
- Show transfer rate, remaining bytes, resume state, and extraction progress.
- Add event-candidate selection instead of only reporting ambiguity.
- Add `list`, `verify`, `clean`, and `open-folder` commands.
- Explain how to enable the CS2 console and run `playdemo`.
- Add automatic Chinese/English output selection with an explicit override.
- Improve recovery guidance for low disk space, missing CS2, permissions,
  Cloudflare changes, and incomplete archives.

Completion criteria:

- A first-time user can complete the workflow using prompts only.
- Cleanup previews every affected file before deletion.
- Human output remains friendly while `--json` stays stable for Agents.

A full graphical interface is not planned until the interactive CLI has been
validated. This avoids maintaining two unstable workflows.

## v0.6.0 — Distribution and Agent ecosystem

**Goal:** make verified releases easy to find, install, and update.

Planned work:

- Publish the Python package to PyPI.
- Publish checksums, an SBOM, and release provenance.
- Submit the Skill to suitable Agent directories and Qoder/TRAE marketplaces.
- Investigate a supported WorkBuddy marketplace package when its `skill.yml`
  import schema is sufficiently documented.
- Add an update/status command with explicit rollback.
- Add short Chinese and English setup videos and troubleshooting guides.
- Define a compatibility test matrix for every advertised Agent and platform.

Completion criteria:

- Public installation does not require a Git checkout for CLI-only users.
- Release artifacts and their checksums can be verified independently.
- Marketplace listings point to the same versioned documentation and tests.

## Longer-term possibilities

These are candidates, not scheduled commitments:

- A provider interface for lawful, stable demo sources other than HLTV.
- Search and organization by event, team, map, date, tags, and favorites.
- Demo metadata indexing and duplicate-content detection.
- Persistent background download queues with pause and resume.
- Read-only MCP tools for listing, verifying, and locating installed demos.
- Native Linux ARM support if the required dependencies and CS2 use case become
  practical.

## Explicit non-goals

- Bypassing HLTV authentication, paywalls, access controls, or rate limits.
- Disabling Agent permission prompts to make automation appear smoother.
- Claiming ordinary Doubao chat support without a documented local Skill or MCP
  interface. TRAE/TraeCode is the supported ByteDance coding-Agent path.
- Downloading every archive in an event by default.
- Silently replacing an existing demo, Skill directory, or unrelated archive.
- Prioritizing macOS CS2 installation while the game itself is unsupported
  there.

## Tracking work

- This file records product direction and release-level acceptance criteria.
- GitHub Issues should contain concrete, reviewable tasks.
- GitHub Milestones should group Issues by target release.
- Completed user-visible changes belong in release notes or a future
  `CHANGELOG.md`, not in this roadmap.

When opening an Issue, include the platform, Agent, command, expected behavior,
actual output, and whether the failure is reproducible with `--dry-run`.
