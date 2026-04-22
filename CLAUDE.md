# claude-repath

Published Python CLI + Claude Code plugin that rewires Claude Code local state
when a project folder is moved or renamed. Distributed on PyPI, GitHub, and
the skills.sh open-standard ecosystem.

## 硬约束

- 必须用 `uv sync --all-groups` 安装开发依赖（不用 `pip install -e .`，`uv_build` 是唯一受支持的 build backend）
- 每次 release 必须同步 bump **四处**版本号，**缺一不可**：
  1. `pyproject.toml` → `[project].version`（PyPI 发布源）
  2. `src/claude_repath/__init__.py` → `__version__`（CLI `--version` 命令输出源）
  3. `.claude-plugin/plugin.json` → `version`（Claude Code plugin 版本）
  4. `.claude-plugin/marketplace.json` → `plugins[0].version`（marketplace 清单）

  漏任何一处都会翻车：v0.3.2 → v0.4.0 漏了 plugin.json/marketplace.json；v0.5.1 漏了 `__init__.py` 导致 PyPI 版本号正确但 `claude-repath --version` 输出错版本。验证命令：`grep -rn "version" pyproject.toml src/claude_repath/__init__.py .claude-plugin/`
- README 所有图片链接必须用 **绝对 URL**（`https://raw.githubusercontent.com/xPeiPeix/claude-repath/main/<file>`）。**禁止**相对路径——PyPI 不渲染相对路径，破图（v0.5.0 踩过）

## 关键路径

- CLI 入口：`src/claude_repath/cli.py`（typer app）
- Skill 定义：`skills/claude-repath/SKILL.md`（skills.sh 通过 `npx skills add xPeiPeix/claude-repath` 自动发现）
- 发布工作流：`.github/workflows/publish.yml`（监听 `release:published` 事件，非 tag push）
- 版本号真源：`pyproject.toml` 的 `[project].version`

## 规则索引

| 文件 | 主题 |
|------|------|
| [.claude/rules/release.md](.claude/rules/release.md) | Release 发版 checklist（版本号三处同步 / CHANGELOG 链接表 / README 绝对 URL 校验 / gh release / PyPI + skills.sh 验证） |
