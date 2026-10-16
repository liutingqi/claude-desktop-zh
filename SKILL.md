---
name: claude-desktop-zh
description: 把 Claude Desktop（macOS）的技能菜单中文化——给 `/` 菜单里每个技能名字后面加中文短标签，并给内置技能（docx/pdf/pptx/xlsx/frontend-design）的悬浮描述加中文摘要。当用户说「Claude 桌面版 skill 菜单是英文」「给插件名加中文说明」「升级后中文又没了」时使用。
---

# Claude Desktop 技能菜单中文化

macOS 上的 Claude Desktop 有两个地方可以本地中文化技能相关的界面，这个技能各配了一个脚本。

## 前置条件

- Claude Desktop 装在 `/Applications/Claude.app`（用 `--app` 可改）。
- 本机有中文补丁项目 `claude-desktop-zh-cn`（MIT，https://github.com/javaht/claude-desktop-zh-cn ）。
  两个脚本都复用它里面久经验证的 asar 读写 / `ElectronAsarIntegrity` 更新 / ad-hoc 重签名逻辑
  （默认路径 `/Users/l/claude-desktop-zh-cn/scripts`，用 `--patch-script-dir` 可改）。
  **不要自己重写签名逻辑**：签错会让 app 直接起不来。

## 用法

```bash
D=/Users/l/.claude/skills/claude-desktop-zh/scripts

# 1) `/` 菜单：技能名字后面加中文短标签（改渲染代码 + 重签名）
python3 "$D/localize_skill_menu.py"

# 2) 内置技能的悬浮描述：中文摘要 + 英文原文（改 app.asar 内清单 + 重签名）
python3 "$D/localize_bundled_skills.py"
```

两个脚本都是幂等的，重复跑只会打印「跳过」。改完**必须重启 Claude Desktop**（退出再打开，不是关窗口）。

改文案时改这两张表，再重跑对应脚本：

- `scripts/skill-labels.zh.json` —— 键是技能标识符（`skillId` 去掉 `插件:` 前缀后的名字，或菜单显示名），值是名字后面那句中文短标签。
- `scripts/bundled-skills.zh.json` —— 键是内置技能的 `name`（**必须是英文原名**），值是中文摘要。

## 两个数据源（关键，改错了不生效）

| 想改的东西 | 真正生效的位置 |
| --- | --- |
| `/` 菜单里技能名后面的文字 | 渲染代码 `Contents/Resources/ion-dist/assets/v1/*.js`（不在 app.asar 里，是松散文件） |
| 技能悬浮提示里的描述 | `app.asar` → `resources/bundled-skills/manifest.json` 的 `description` |

`~/Library/Application Support/Claude-3p/.../cowork_plugins/cache/**` 下的插件缓存**不影响**菜单显示——改那里的 `SKILL.md` 是白费功夫。

## 硬规则

- 只改 `description` 和显示逻辑，**绝不改技能的 `name` / `skillId`**。name 是标识符：它拼出 `skillId`（`bundled:docx`）、决定 `${name}.skill` 的文件查找、还会进入系统提示。
- 任何改动都要重签名，否则 app 校验失败。脚本会自动调用重签名（`--no-resign` 可跳过，但跳过之后 app 起不来）。
- 动手前先确认能回滚：`localize_skill_menu.py` 会在同目录留 `.bak-zh-skilllabel` 备份。

## 验证与回滚

```bash
D=/Users/l/.claude/skills/claude-desktop-zh/scripts
python3 "$D/localize_skill_menu.py" --restore     # 还原菜单渲染代码并重签名

# 签名与 asar 完整性
codesign --verify /Applications/Claude.app && echo 签名 OK
python3 -I -c "import sys;sys.path.insert(0,'/Users/l/claude-desktop-zh-cn/scripts');
import patch_claude_zh_cn as p;from pathlib import Path
p.verify_electron_asar_integrity(Path('/Applications/Claude.app'))"
```

改完渲染代码后，可以先把那个 JS 拷成 `.mjs` 跑 `node --check` 验语法再重签名。

## 升级后失效怎么办

Claude Desktop 自动更新会覆盖两处改动（`app.asar` 会被整体替换，`ion-dist` 下的哈希文件名也会变）。更新后重跑上面两条命令即可。

如果脚本报「未找到菜单行锚点」，说明新版把渲染代码改了，按 `references/findings.md` 里记录的定位方法重新找锚点，再更新脚本里的 `ANCHOR`。

## 已知限制

- **代理技能**（`schedule`、`setup-claude`、`setup-cowork`、`consolidate-memory`、`explain-usage`、`context`）的名称与描述疑似远程下发，本地改不到；脚本的标签表能按名字给它们加中文短标签，但悬浮描述改不了。
- 插件市场里同一批技能被多个插件重复打包（19 个技能 × 5 个插件），`/` 菜单按名字去重后仍会显示多条同名项——那是 Anthropic 的打包方式，不是本地改动造成的。
- 只支持 macOS 上的 Claude Desktop。

技术细节（数据源链路、锚点、去重逻辑、验证证据）见 `references/findings.md`。
