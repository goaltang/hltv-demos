# hltv-demos

从 HLTV 查找、下载、校验并安装 CS2 GOTV demo。

## 支持范围

v0.3 支持 **Linux x86-64** 和 **Windows WSL2**，需要 Python 3.10 以上。
目前不自动支持原生 Windows、macOS 和 Linux ARM。

工具需要访问外网，并写入 CS2 的 `game/csgo` 目录。默认把压缩包保存在
`~/Downloads`，状态文件和经过校验的 `7zz` 保存在 `~/tools/hltv-demos`。

## 新手安装

```bash
git clone https://github.com/goaltang/hltv-demos.git
cd hltv-demos
./scripts/install --agent auto
./scripts/doctor
```

也可以指定 Agent：

```bash
./scripts/install --agent claude
./scripts/install --agent codex
./scripts/install --agent cursor
```

安装器会在 `~/.local/share/hltv-demos/venv` 创建独立环境，不会覆盖已经
存在的 Skill 目录。

## 安全使用流程

先查看计划，不会下载录像：

```bash
./scripts/hltv-demos   --event '完整的 HLTV 赛事网址'   --maps '荒漠迷城,炼狱小镇' --latest 3 --dry-run
```

确认赛事、比赛、预计大小和目录都正确后，再执行：

```bash
./scripts/hltv-demos   --event '完整的 HLTV 赛事网址'   --maps '荒漠迷城,炼狱小镇' --latest 3 --yes
```

真实下载必须提供 `--yes`。默认保留压缩包；只有明确需要时才使用
`--no-keep-rars`。

## 常见问题

- 运行 `./scripts/doctor` 检查系统、CS2 路径和 7-Zip。
- `--csgo-dir` 可以填写游戏根目录，也可以直接填写 `game/csgo`。
- `--download-dir` 可以更改压缩包目录。
- 如果赛事名称有歧义，工具会停止并显示候选项，不会自行猜测。
- 下载中断后再次运行相同命令，会从 `.part` 文件继续。
- 工具不会覆盖大小异常的已有 demo。
- 首次需要 7-Zip 时，只会执行 SHA-256 校验通过的官方 Linux x64 文件。

更完整的技术说明参见 [README.md](README.md)。

## 许可证

[MIT](LICENSE)
