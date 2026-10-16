# claude-desktop-zh

把 macOS 版 Claude Desktop 的**技能菜单中文化**的 Claude Code 技能。

装好之后，`/` 菜单里每个技能的名字后面会多出一句中文短标签（比如 `docx  Word 文档`），
内置文档技能的悬浮描述也会变成「中文摘要 + 英文原文」。再也不用把鼠标悬上去猜这个 skill 是干嘛的。

```
/ 菜单                     改动后
┌──────────────────────┐   ┌────────────────────────────────┐
│ docx                 │   │ docx    Word 文档              │
│ pdf                  │   │ pdf     PDF 处理               │
│ pptx                 │   │ pptx    PPT 演示               │
│ schedule             │   │ schedule 定时任务              │
└──────────────────────┘   └────────────────────────────────┘
```

## 依赖

- macOS + 装在 `/Applications/Claude.app` 的 Claude Desktop
- [claude-desktop-zh-cn](https://github.com/javaht/claude-desktop-zh-cn)（MIT）的 `scripts/` 目录。
  本技能复用它里面久经验证的 asar 读写、`ElectronAsarIntegrity` 更新和 ad-hoc 重签名逻辑，
  **不自己造签名轮子**——签错会让 app 直接起不来。
  默认路径 `/Users/l/claude-desktop-zh-cn/scripts`，用 `--patch-script-dir` 改。

## 安装

```bash
git clone <本仓库> ~/.claude/skills/claude-desktop-zh
```

## 用法

```bash
D=~/.claude/skills/claude-desktop-zh/scripts

python3 "$D/localize_skill_menu.py"        # 技能名后面加中文短标签
python3 "$D/localize_bundled_skills.py"    # 内置技能的悬浮描述加中文摘要
```

两个脚本都幂等，重复执行只会打印「跳过」。改完**退出并重新打开** Claude Desktop 才生效。

改文案不用动代码，只改这两张表再重跑：

| 文件 | 作用 |
| --- | --- |
| `scripts/skill-labels.zh.json` | 名字后面那句中文短标签，键是技能标识符 |
| `scripts/bundled-skills.zh.json` | 内置技能的中文摘要，键必须保持英文原名 |

## 回滚

```bash
python3 scripts/localize_skill_menu.py --restore   # 还原渲染代码并重签名
```

首次改动前脚本会在原文件旁留 `.bak-zh-skilllabel` 备份。

## 它是怎么做的

菜单行只内联渲染「图标 / 名字 / 别名 / 副标题 / 角标」，技能描述**只在悬浮气泡里**，
也没有纯数据的方式能把中文塞到名字后面。所以本技能：

1. 在 `ion-dist/assets/v1/*.js` 里按唯一锚点定位菜单行渲染代码，在名字 span 之后插入一个
   条件渲染的 span（全目录搜锚点，不写死哈希文件名）；
2. 标签按 `skillId`（去掉 `插件:` 前缀）→ 菜单显示名 → 描述首行的顺序解析；
3. 改 `app.asar` 里 `resources/bundled-skills/manifest.json` 的 `description`，
   写成「中文摘要 + 英文原文」，只改描述，**绝不改 `name`**；
4. 最后对整个 app 重签名（保留 identifier DR，自动更新仍能校验）。

技术细节见 `references/findings.md`。

## 已知限制

- Claude Desktop 自动更新会覆盖这两处改动，升级后重跑脚本即可。
- 代理技能（`schedule`、`setup-claude`、`consolidate-memory`、`explain-usage` 等）的描述疑似远程下发，本地改不到；短标签仍能按名字加上。
- 只支持 macOS。
