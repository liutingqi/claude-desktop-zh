# 定位笔记（版本相关，升级后可能变化）

记录时间：2026-10-16，基于当时最新的 Claude Desktop（macOS）。

## 1. `/` 菜单里技能副标题的数据源

`/` 菜单的技能对象由**主进程**产出：主进程读 `app.asar` 内的
`resources/bundled-skills/manifest.json`，把每个技能的 `description` 映射成菜单对象
`{skillId, name, description, ...}`（主进程代码在 `.vite/build/index.chunk-*.js`）。

所以：

- 改这个 manifest 的 `description` → 菜单悬浮提示变化 ✅
- 改 `cowork_plugins/cache/**/SKILL.md` → 菜单**毫无变化** ❌

`manifest.json` 结构：`{"skills": [{"name","description","tier":"always"}, ...]}`，共 6 条
（docx、pdf、pdf-reading、pptx、xlsx、frontend-design）。

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

## 3. 为什么 `/` 菜单里不会有「同名重复」

聚合逻辑在 `ce1dac304-*.js`：合并 4 个来源后用 `uniqBy`（`shared-104-*.js` 的 `jd`/`tp`）去重，
去重键是 `d(e.name).toLowerCase()`，其中 `d`（`c40a790d4-*.js` 的 `n`）会砍掉 `:` 之前的插件前缀。
保留第一条，所以菜单里同名技能只会出现一次。

用户看到的「技能重复」来自插件市场打包方式：`anthropic-agent-skills` 市场下的 5 个插件
（document-skills、academy-guide、claude-api、discernment-nudge、example-skills）各自打包了
**同一批 19 个技能**，40 个技能目录里 19 个名字各出现 5 次。与中文化改动无关。

## 4. 验证做法

- 语法：把改完的 JS 拷成 `.mjs`，`node --check`。
- 逻辑：把 `/*zh-skill-label*/` 到 `,t)` 之间的片段抽出来，前面补一个
  `const s=(t,p)=>({tag:t,props:p})` 桩，末尾把 `,t)` 换成 `,o)`，用假菜单项跑一遍，
  检查中英文/超长/无映射各种输入。
- 落盘：`codesign --verify` + `verify_electron_asar_integrity`。

## 5. 备份与回滚

- `localize_skill_menu.py` 首次注入前会在同目录写 `<chunk>.js.bak-zh-skilllabel`，
  `--restore` 从它还原。
- 早期手工改 `cowork_plugins` 留下的 `.bak-2026-10-16` 备份与本技能无关。
