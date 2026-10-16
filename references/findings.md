# 定位笔记（版本相关，升级后可能变化）

记录时间：2026-10-16，基于当时最新的 Claude Desktop（macOS）。

## 1. `/` 菜单里技能副标题的数据源

`/` 菜单的技能对象由**主进程**产出：主进程读 `app.asar` 内的
`resources/bundled-skills/manifest.json`，把每个技能的 `description` 映射成菜单对象
`{skillId, name, description, ...}`（主进程代码在 `.vite/build/index.chunk-*.js`）。

所以：

- 改这个 manifest 的 `description` → **内置 6 个技能**的悬浮提示变化 ✅
- 改 `cowork_plugins/cache/**/SKILL.md` → 菜单**毫无变化** ❌

`manifest.json` 结构：`{"skills": [{"name","description","tier":"always"}, ...]}`，共 6 条
（docx、pdf、pdf-reading、pptx、xlsx、frontend-design）。

剩下 90 多个插件技能的描述来自插件系统，与这份 manifest 无关。两条来源最终都汇成
菜单项对象的 `skillDescription` 字段——所以**改渲染代码是唯一一处就能覆盖全部技能的办法**
（见第 2 节的第二处注入），比逐处追数据源省事得多。

## 2. 菜单行的渲染代码

文件：`Contents/Resources/ion-dist/assets/v1/ccc334009-Dm5Xsw5s.js`（文件名带内容哈希，升级后会变）。
它由 `shared-5-*.js` 懒加载注册，id 是 `slash_command_menu`，导出
`{X as SlashCommandMenuPopupBody, q as _test}`。

技能行（`t.type==="skill"||t.type==="connector-tool"`）**只会内联渲染**：

```
图标 → 名字(label) → 命中的别名(${alias}) → 副标题(subtitle，ms-auto 右对齐) → 角标(badge)
```

`skillDescription` **只喂给悬浮气泡**（`c17e03edc-*.js` 里的 popper），`argumentHint` 在这个文件里
出现 0 次、根本不渲染；`subtitle` 只有 `type:"button"` 的行才会被赋值，技能行始终是 `undefined`。
结论：想让中文出现在名字后面，只能改渲染代码——没有纯数据的办法。

### 锚点

```
className:"min-w-0 truncate",children:s(j,{text:t.label,query:v,highlightClassName:"font-semibold"})})
```

- 全目录唯一（`grep -o` 计数 = 1）。
- **末尾的 `})})` 不能少**：少了就把插入的表达式插进外层 `span` 的 props 对象里，JS 直接语法错误
  （实测：`node --check` 报 `SyntaxError: Unexpected token '('`）。
- 插入的表达式是一个自调用箭头函数 `((_m,_o)=>{...})({标签表}, t)`，`t` 就是当前菜单项
  （行组件签名是 `function G({item:t,...})`）。它作为 `children:[...]` 数组的一个元素插入，
  解析不到标签时返回 `null`，React 会忽略。
- 脚本用 `/*zh-skill-label*/` 标记判断是否已插入，避免重复注入。

### 标签的解析顺序

1. 标签表里以 `skillId.split(":").pop()` 小写为键（`bundled:docx` → `docx`）；
2. 标签表里以菜单显示名为键；
3. 兜底：描述第一行含中文且 ≤ 20 字符时直接用该行。

### 第二处注入：悬浮气泡里的中文概要

气泡由**同一个文件**里的 `SlashCommandMenuPopupBody`（`function Y()`）渲染，
所以不用去别处找数据源。取值点只有一句：

```js
let{items:e,activeIndex:t,...}=O(),d=T(),m=D(),_=e[t],y=_?.type==="skill"?_:null,
    b=y?y.skillDescription:_&&"subtitle"in _?_.subtitle:void 0,   // ← 锚点
    x=b||y?.sourcePluginName||y?.sourceRepo?_:null,...
...
children:x&&s(N,{description:b,sourcePluginName:y?.sourcePluginName,sourceRepo:y?.sourceRepo,query:r})
```

锚点：`b=y?y.skillDescription:_&&"subtitle"in _?_.subtitle:void 0,`（全目录唯一）。

**两个坑（第二个只有跑起来才会暴露）：**

1. 它在 `let` 声明列表里，所以替换结果必须是**单个表达式**——不能写成
   `b=...,b=...`，`let` 声明列表里重复声明同名绑定是 SyntaxError。
2. 更不能在新表达式里读写 `b`（例如把 `b=...` 整条当参数传进去）。`b` 此刻还在 TDZ 里，
   运行时会抛 `ReferenceError`，整个菜单直接崩——**而 `node --check` 是过得去的**
   （语法合法），只有真的执行到那一行才发现。所以原表达式要作为参数整体传入：
   `b=((_d,_b)=>{...})({概要表}, y?y.skillDescription:_&&"subtitle"in _?_.subtitle:void 0)`。

同一函数里还有 `x=b||y?.sourcePluginName||y?.sourceRepo?_:null` 决定气泡显不显示，
描述为空时返回原值即可保持原行为。

解析顺序与短标签一致；命中后返回 `概要 + "\n" + 原文`。原文首行已含中文（内置技能的
描述此前被 `localize_bundled_skills.py` 改过）或不是字符串时**原样返回**，避免中文叠两层、
以及把 react-intl 描述符拼成 `[object Object]`。

## 3. 为什么 `/` 菜单里不会有「同名重复」

聚合逻辑在 `ce1dac304-*.js`：合并 4 个来源后用 `uniqBy`（`shared-104-*.js` 的 `jd`/`tp`）去重，
去重键是 `d(e.name).toLowerCase()`，其中 `d`（`c40a790d4-*.js` 的 `n`）会砍掉 `:` 之前的插件前缀。
保留第一条，所以菜单里同名技能只会出现一次。

用户看到的「技能重复」来自插件市场打包方式：`anthropic-agent-skills` 市场下的 5 个插件
（document-skills、academy-guide、claude-api、discernment-nudge、example-skills）各自打包了
**同一批 19 个技能**，40 个技能目录里 19 个名字各出现 5 次。与中文化改动无关。

## 4. 验证做法

**先试跑，再落盘**——脚本在真正写入前会把注入结果拼好，务必走完前两步：

- 语法：把改完的 JS 拷成 `.mjs`，`node --check`。**注意这一步查不出 TDZ 问题**（见第 2 节坑 2）。
- 逻辑：把 `/*zh-skill-label*/` 到 `,t)` 之间的片段抽出来，前面补一个
  `const s=(t,p)=>({tag:t,props:p})` 桩，末尾把 `,t)` 换成 `,o)`，用假菜单项跑一遍，
  检查中英文/超长/无映射各种输入。
  气泡那段更简单：把 `/*zh-skill-desc*/` 与 `/*zh-skill-desc-end*/` 之间的内容抠出来，
  去掉开头的 `b=` 和结尾的逗号，用 `new Function("y","_",'return ('+expr+')')` 直接调用，
  覆盖「英文描述 / 已含中文的描述 / 表里没有的键 / 描述为 undefined / 描述不是字符串」五种输入。
- 落盘：`codesign --verify --deep --strict` + `verify_electron_asar_integrity`。
- 真实生效：退出并重开 Claude Desktop。气泡只在悬停**非第一行**时出现（原版逻辑）。

## 5. 备份与回滚

备份放在 `~/Library/Application Support/claude-desktop-zh/.app-backups/`（按 chunk 文件名存放，
升级换了哈希名后由 `prune_stale_backups` 自动清理），`--restore` 从它还原。

**位置为什么讲究**（2026-10-16 安全复查后调整）：备份的内容会被**原样写回已签名的 app**，
等于要执行的代码，属于可信输入，所以两条都不能违反：

- **不能放 `.app/` 里**：会被 codesign 封进签名，之后删掉它就报
  "a sealed resource is missing or invalid"。早期版本就是这么干的（`.bak-zh-skilllabel`
  放同目录），脚本里保留了迁移逻辑把旧备份挪出来。
- **不能放技能目录里**：早期用的是技能目录内的 `.app-backups/`，但那在 git 仓库工作树里——
  一个能被 `git clean -xdf` 清掉、能被同步、能被打包进分发的目录，不该同时是
  「写进签名 app 的内容」的来源。现在只作为迁移来源读（`LEGACY_BACKUP_DIR`）。

**信任链**（`read_original`，从高到低）：

1. bundle 里当前的文件只要**没打过补丁**就是原文——app 升级后正是这种情况，直接用它；
2. 备份目录里**带 sha256 记录且校验通过**的备份（`index.json`）；
3. 旧版遗留位置（`LEGACY_BACKUP_DIR`、bundle 内的 `.bak-zh-skilllabel`）——没有哈希可查，
   必须过 `accept_unverified` 的结构校验（不含补丁标记、`ANCHOR` 恰好出现一次）。

任何一步不过就 `SystemExit`，**不猜、不降级**。`--restore` 写回前同样先校验哈希。

一个易踩的坑：删掉 bundle 内的旧备份等于动了**被封进签名的资源**，必须重签名，
所以 `read_original` 在那条路径上要返回 `dirty=True` 触发重签；否则「改了 bundle 却没重签」
会让 app 起不来。只搬外部备份文件则不需要重签。

早期手工改 `cowork_plugins` 留下的 `.bak-2026-10-16` 备份与本技能无关。
