# hltv-demos

安全地查找、下载、校验并安装 HLTV CS2 GOTV demo。

## 支持范围

v0.3.1 支持 **Linux x86-64** 和 **Windows WSL2**，需要 Python 3.10 以上。
目前不自动支持原生 Windows、macOS 和 Linux ARM。

## 新手安装

```bash
git clone https://github.com/goaltang/hltv-demos.git
cd hltv-demos
./scripts/install --agent auto
./scripts/doctor
```

也可以指定 Agent：

```bash
./scripts/install --agent qoder
./scripts/install --agent trae
./scripts/install --agent claude --agent cursor
./scripts/install --agent all
```

| Agent | 用户级 Skill 目录 |
|---|---|
| Prime Agent | `~/.prime/agent/skills/` |
| Claude Code | `~/.claude/skills/` |
| OpenAI Codex | `~/.agents/skills/` |
| Cursor | `~/.cursor/skills/` |
| Gemini CLI | `~/.gemini/skills/` |
| Qoder | `~/.qoder/skills/` |
| TRAE / TraeCode | `~/.trae/skills/` |

TRAE 也会读取共享的 `~/.agents/skills/`。安装器会在
`~/.local/share/hltv-demos/releases/` 创建版本化独立环境，并通过
`current` 原子切换版本。它不会覆盖无关的已有 Skill。

## 安全使用

先查看计划，不下载录像：

```bash
./scripts/hltv-demos   --event '完整的 HLTV 赛事网址'   --maps '荒漠迷城,炼狱小镇' --latest 3 --dry-run
```

确认赛事、比赛、大小和目录后再执行：

```bash
./scripts/hltv-demos   --event '完整的 HLTV 赛事网址'   --maps '荒漠迷城,炼狱小镇' --latest 3 --yes
```

真实下载必须提供 `--yes`。默认保留压缩包；只有明确需要时才使用
`--no-keep-rars`。

## WorkBuddy

WorkBuddy 使用自己的 `skill.yml`，不能直接安装本项目的 `SKILL.md`。
本项目为它提供了本地 stdio MCP 适配器。在 WSL2 内单独安装 MCP 依赖后运行：

```bash
./scripts/install --with-mcp --agent auto
./scripts/workbuddy-mcp-config > workbuddy-hltv-mcp.json
```

把生成的 `mcpServers.hltv-demos` 配置合并到 WorkBuddy 的
`~/.workbuddy/mcp.json`。保持默认/手动审批模式，不要为了省事开启 Full Access。

MCP 提供环境检查、只读计划和执行已批准计划三个工具。执行令牌十分钟后
失效且只能使用一次；执行内容固定为用户看到的比赛、URL、大小和目录，
不会在执行时重新搜索并替换比赛。

普通豆包桌面端/网页端目前没有公开的任意 `SKILL.md` 或本地 MCP 导入方式。
字节系编程场景请使用 **TRAE/TraeCode**，不要把普通豆包当成本地编码 Agent。

## 后续路线

- v0.3.2：真实端到端验证、manifest 并发锁和真实 Agent 客户端测试。
- v0.4.0：原生 Windows 和 Steam 库发现。
- v0.5.0：新手交互流程和录像管理。
- v0.6.0：PyPI、发布来源证明和 Agent 市场分发。

详细优先级、完成标准和明确不做的内容见
[ROADMAP.zh-CN.md](ROADMAP.zh-CN.md)。

## 常见问题

- 运行 `./scripts/doctor` 检查系统、CS2 路径和 7-Zip。
- `--csgo-dir` 可填写游戏根目录或最终的 `game/csgo`。
- `--download-dir` 可更改压缩包目录。
- 模糊赛事会停止并显示候选项，不会自动猜测。
- 下载中断后再次运行相同命令，会从 `.part` 文件继续。
- 工具不会覆盖大小异常的已有 demo。
- 首次需要 7-Zip 时，只执行 SHA-256 校验通过的官方 Linux x64 文件。

完整技术说明参见 [README.md](README.md)。

## 许可证

[MIT](LICENSE)
