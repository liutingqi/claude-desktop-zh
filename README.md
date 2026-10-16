# claude-desktop-zh

把 macOS 版 Claude Desktop 的**技能菜单中文化**的 Claude Code 技能。

装好之后，`/` 菜单里每个技能的名字后面会多出一句中文短标签（比如 `docx  Word 文档`），
鼠标悬浮上去的气泡里，中文概要排在英文原文上面一行。
再也不用把鼠标悬上去猜这个 skill 是干嘛的。

```
/ 菜单                     改动后
┌──────────────────────┐   ┌────────────────────────────────┐
│ docx                 │   │ docx    Word 文档              │
│ pdf                  │   │ pdf     PDF 处理               │
│ pptx                 │   │ pptx    PPT 演示               │
│ schedule             │   │ schedule 定时任务              │
└──────────────────────┘   └────────────────────────────────┘

悬浮气泡（改动后）：
  ┌────────────────────────────────────────────────────────┐
  │ 创建、读取和编辑 Word 文档与模板，需要修订或批注时使用。  │
  │ Create, read and edit Word documents and templates…    │
  └────────────────────────────────────────────────────────┘
```

## 依赖

- macOS + 装在 `/Applications/Claude.app` 的 Claude Desktop
- [claude-desktop-zh-cn](https://github.com/javaht/claude-desktop-zh-cn)（MIT）的 `scripts/` 目录。
  本技能复用它里面久经验证的寻址与 ad-hoc 重签名逻辑（`resign_app`），
  **不自己造签名轮子**——签错会让 app 直接起不来。
  默认路径 `/Users/l/claude-desktop-zh-cn/scripts`，用 `--patch-script-dir` 改。

## 安装

```bash
git clone https://github.com/liutingqi/claude-desktop-zh.git ~/.claude/skills/claude-desktop-zh
```

## 用法

```bash
D=~/.claude/skills/claude-desktop-zh/scripts

python3 "$D/localize_skill_menu.py"              # 把两张表注入渲染代码
python3 "$D/sync_skill_labels.py"                # 只报告：哪些新技能还没中文
python3 "$D/sync_skill_labels.py" --apply        # 翻译缺失项 + 写表 + 重打补丁 + 重签名
```

**装了新技能之后**只需要跑一次 `sync_skill_labels.py --apply`：它会扫描本机所有技能
（内置的、插件的都扫），把缺的中文短标签和中文概要翻译好写进两张表，再自动重打补丁。
翻译走你自己配的网关，技能名和描述会发到那个网关；不想外发的写进 `scripts/.skip-translate`。

所有脚本都幂等，重复执行只会打印「跳过」。改文案不用动代码，只改表再重跑。
改完**退出并重新打开** Claude Desktop 才生效。

| 文件 | 作用 |
| --- | --- |
| `scripts/skill-labels.zh.json` | 名字后面那句中文短标签，键是技能标识符 |
| `scripts/skill-summaries.zh.json` | 悬浮气泡里的中文概要，键是技能标识符 |

## 回滚

```bash
python3 scripts/localize_skill_menu.py --restore   # 还原渲染代码并重签名
```

首次改动前脚本把原始文件备份到 bundle **外面**的 `.app-backups/`
（放进 bundle 里会被 codesign 封进签名，之后删掉它就会报
"a sealed resource is missing or invalid"）。

## 它是怎么做的

菜单行只内联渲染「图标 / 名字 / 别名 / 副标题 / 角标」，技能描述**只在悬浮气泡里**，
也没有纯数据的方式能把中文塞到名字后面。所以本技能只改渲染代码：

1. 在 `ion-dist/assets/v1/*.js` 里按唯一锚点定位菜单行渲染代码
   （全目录搜锚点，不写死哈希文件名，升级后仍能定位）；
2. 在名字 span 之后插入一个条件渲染的 span —— 中文短标签，
   按 `skillId`（去掉 `插件:` 前缀）→ 菜单显示名 → 描述首行的顺序解析；
3. 在同一个文件的悬浮气泡里，把 description 的取值点换成
   「中文概要 + 换行 + 英文原文」；原文首行已经含中文时原样返回，避免中文叠两层；
4. 最后对整个 app 重签名（保留 identifier DR，自动更新仍能校验）。

**为什么不直接改各技能的 SKILL.md？** 那是插件缓存、会被插件更新覆盖、改了还会进模型
上下文，而且没有备份就退不回来。渲染侧注入只影响菜单显示，内置和插件技能一视同仁。

技术细节见 `references/findings.md`。

## 已知限制

- Claude Desktop 自动更新会覆盖渲染代码改动，升级后重跑脚本即可
  （备份是按文件名匹配的，升级换了哈希文件名时旧备份会自动清理）。
- 只支持 macOS。
