# Release Checklist

每次发 release 严格按序执行。跳步 = 翻车（v0.5.0 PyPI demo 破图就是跳了 README 绝对 URL 校验）。

## 1. 预检（改动前）

- [ ] `git status` 干净，work tree clean、跟 `origin/main` 同步
- [ ] 所有测试通过：`uv run pytest`
- [ ] `uv run ruff check` 无告警

## 2. 版本号同步（**四处**必改，缺一不可）

- [ ] `pyproject.toml` → `[project].version`（PyPI 发布源）
- [ ] `src/claude_repath/__init__.py` → `__version__`（CLI `--version` 命令输出源）
- [ ] `.claude-plugin/plugin.json` → `version`（Claude Code plugin 版本）
- [ ] `.claude-plugin/marketplace.json` → `plugins[0].version`（marketplace 清单）

四处必须完全一致。漏改教训：
- v0.3.2 → v0.4.0：两个 json 停在 0.3.2，直到 v0.4.1 修复
- v0.5.1：`__init__.py` 漏改，PyPI 版本正确但 `claude-repath --version` 输出 0.5.0，v0.5.2 紧急补发修复

**一键验证**：
```bash
grep -Hn "version\|__version__" pyproject.toml src/claude_repath/__init__.py .claude-plugin/*.json
# 输出四行必须是同一版本号
```

## 3. CHANGELOG

- [ ] `CHANGELOG.md` 新增 `## [X.Y.Z] — YYYY-MM-DD` 段落（Added / Changed / Fixed / Removed 分类）
- [ ] 文末链接表更新：
  - [ ] `[Unreleased]: .../compare/vX.Y.Z...HEAD` 指向最新版
  - [ ] 新增 `[X.Y.Z]: .../compare/v<prev>...vX.Y.Z`

## 4. README 校验

- [ ] 所有 `![...](path)` 图片链接必须是 **绝对 URL**：`https://raw.githubusercontent.com/xPeiPeix/claude-repath/main/<file>`
  - **禁止**相对路径 `./demo.gif` — PyPI 不渲染相对路径，破图（v0.5.0 翻车案例）
- [ ] badges 链接指向正确的默认分支（`main`，不是 `master`）
- [ ] Install 章节同时覆盖三条路径：PyPI CLI（uvx/pipx/pip）、Claude Code plugin（`/plugin marketplace add`）、skills.sh 生态（`npx skills add xPeiPeix/claude-repath`）
- [ ] **Roadmap 段更新**（极易漏）：
  - [ ] 原来的 `**vA.B.C (current)**` 去掉 `(current)` 标签
  - [ ] 在顶部插入 `**vX.Y.Z (current)**` 新条目，技术性段落描述核心变更（风格参考旧条目）
  - [ ] 验证：`grep "(current)" README.md` 只出现一次，且是新版
  - 历史教训：v0.9.0 / v0.9.1 连续两次 release 都漏了这条，PyPI 和 README 上新版已发布但 Roadmap 仍指向 v0.8.2。这条单独列成 checklist 就是因为容易漏。

## 5. Commit + Tag + Release（三步，不可合并）

```bash
# 5.1 commit（中文、≤50 字、禁止 Co-Authored-By 行）
git add pyproject.toml .claude-plugin/ CHANGELOG.md README.md <其他改动>
git commit -m "release vX.Y.Z: 一句话摘要"

# 5.2 push
git push origin main

# 5.3 打 annotated tag 并 push
git tag -a vX.Y.Z -m "Release X.Y.Z"
git push origin vX.Y.Z

# 5.4 创建 GitHub release（触发 publish.yml）
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "$(awk '/^## \[X.Y.Z\]/{flag=1;next}/^## \[/{flag=0}flag' CHANGELOG.md)"
```

⚠️ **必须用 `gh release create`**（不是只 push tag）。`.github/workflows/publish.yml` 监听 `release: published` 事件，单独 push tag 不触发 PyPI 自动发布。

## 6. 发布后验证

- [ ] GitHub Actions publish.yml 绿灯：<https://github.com/xPeiPeix/claude-repath/actions/workflows/publish.yml>
- [ ] PyPI 页面 demo.gif 正常显示、版本号更新：<https://pypi.org/project/claude-repath/>
- [ ] `uvx --from claude-repath@X.Y.Z claude-repath --version` 拉到新版号
- [ ] `npx skills add xPeiPeix/claude-repath -y` 能识别 `skills/claude-repath/SKILL.md` 并完成安装（贡献 skills.sh install 计数）

## 踩过的坑

1. **v0.5.0 PyPI demo 破图** — README 用相对路径 `./demo.gif`，PyPI 不解析 → v0.5.1 改绝对 raw URL 修复。**PyPI 不会追溯渲染旧版 README**，v0.5.0 页面永远破图，只能发新版让最新版恢复。
2. **plugin.json / marketplace.json 版本遗忘** — v0.3.2 → v0.4.0 升级时两个 json 没同步 bump，停留在 0.3.2，直到 v0.4.1 才发现并修复（见 CHANGELOG v0.4.1 "Fixed" 末条）。第 2 节三处 checklist 就是为此设立。
