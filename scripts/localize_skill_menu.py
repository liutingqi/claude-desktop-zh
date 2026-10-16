#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Claude Desktop 的 `/` 菜单里，给技能名字后面加一段中文短标签。

背景
----
菜单行的渲染代码（`ion-dist/assets/v1/<hash>.js` 里的 SlashCommandMenuPopupBody）
只内联渲染「图标 + 名字 + 命中的别名 + 副标题」，技能描述 **只在鼠标悬浮的气泡里**。
所以想让中文出现在名字后面，必须给渲染代码插一行。

做法（只改数据 + 一处渲染代码，绝不改技能 name / skillId）
-----------------------------------------------------------
1. 找到含锚点 `className:"min-w-0 truncate",children:s(j,{text:t.label,...})` 的 JS 文件
   （全目录唯一，不写死哈希文件名，升级后仍可定位）。
2. 在该名字 span 之后插入一个条件渲染的 span，文本按以下顺序解析：
   a. `skill-labels.zh.json` 里以 skillId（去掉 `插件:` 前缀）为键的标签；
   b. 同一张表里以菜单显示名为键的标签；
   c. 兜底：该技能描述的第一行，若含中文且不超过 20 字符。
3. ad-hoc 重签名整个 app（保持 identifier DR，自动更新仍可校验）。

依赖
----
复用中文补丁脚本 https://github.com/javaht/claude-desktop-zh-cn （MIT）里的
asar 读写 / ElectronAsarIntegrity 更新 / 重签名逻辑。用 --patch-script 指定其目录。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_PATCH_SCRIPT_DIR = Path("/Users/l/claude-desktop-zh-cn/scripts")
DEFAULT_APP = Path("/Applications/Claude.app")
LABEL_FILE_NAME = "skill-labels.zh.json"

# 菜单行里「技能名字」那个 span 的唯一锚点（升级后若变，脚本会报错而不是乱改）。
# 末尾的 "})})" 是必须的：把整个 span 收尾包进来，插入的表达式才会落在
# 外层 children 数组元素之间，而不是掉进 span 的 props 对象里。
ANCHOR = (
    'className:"min-w-0 truncate",children:s(j,{text:t.label,'
    'query:v,highlightClassName:"font-semibold"})})'
)
MARKER = "zh-skill-label"

def build_inject(labels: dict[str, str]) -> str:
    """生成插入菜单行的渲染表达式（一个自调用箭头函数）。

    - `_m` 是中文标签表，`_o` 是当前菜单项；
    - 保留 marker，便于重复执行时跳过；
    - 注意 `"\\n"` 是 JS 字符串转义，必须保持字面反斜杠 n。
    """
    return (
        ",/*" + MARKER + "*/"
        "((_m,_o)=>{"
        'let _k=(((_o.skillId||"")+"").split(":").pop()||"").trim().toLowerCase();'
        'let _v=_m[_k]||_m[(((_o.label||"")+"").trim().toLowerCase())]||"";'
        "if(!_v){"
        'let _f=(((_o.skillDescription||"")+"")||"").split("\\n")[0].trim();'
        '_v=_f.length<=20&&/[\\u4e00-\\u9fff]/.test(_f)?_f:""}'
        'return _v?s("span",{className:"ms-2 shrink-0 text-caption text-muted-as-secondary",'
        "children:_v}):null})(" + js_map(labels) + ",t)"
    )


def load_labels(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(k): str(v)
        for k, v in data.items()
        if not k.startswith("_") and isinstance(v, str) and v
    }


def js_map(labels: dict[str, str]) -> str:
    return json.dumps(labels, ensure_ascii=False, separators=(",", ":"))


def patch_frontend(assets_dir: Path, labels: dict[str, str]) -> Path | None:
    hits: list[Path] = []
    for path in sorted(assets_dir.glob("*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if ANCHOR in text:
            hits.append(path)

    if not hits:
        raise SystemExit(
            f"未在 {assets_dir} 找到菜单行锚点，可能新版 Claude 改了渲染代码，请重新定位。"
        )
    if len(hits) > 1:
        raise SystemExit("锚点命中多个文件，为安全起见中止：" + ", ".join(p.name for p in hits))

    path = hits[0]
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"  [跳过] {path.name} 已插入过中文标签")
        return None
    if text.count(ANCHOR) != 1:
        raise SystemExit(f"锚点在 {path.name} 中出现 {text.count(ANCHOR)} 次，中止。")

    patched = text.replace(ANCHOR, ANCHOR + build_inject(labels), 1)
    backup = path.with_suffix(path.suffix + ".bak-zh-skilllabel")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(patched, encoding="utf-8")
    print(f"  [ok] {path.name}：已在技能名字后插入中文标签渲染")
    print(f"       备份：{backup.name}")
    return path


def restore_frontend(assets_dir: Path) -> bool:
    """把菜单渲染代码还原成插入前的版本（从 .bak-zh-skilllabel 备份）。"""
    for backup in sorted(assets_dir.glob("*.js.bak-zh-skilllabel")):
        original = backup.with_suffix("")
        shutil.copy2(backup, original)
        print(f"  [ok] 已从 {backup.name} 还原 {original.name}")
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description="在 Claude Desktop 的 / 菜单里给技能名字后面加中文短标签"
    )
    ap.add_argument("--app", type=Path, default=DEFAULT_APP)
    ap.add_argument(
        "--patch-script-dir",
        type=Path,
        default=DEFAULT_PATCH_SCRIPT_DIR,
        help="claude-desktop-zh-cn 的 scripts 目录（提供 asar 读写与重签名）",
    )
    ap.add_argument(
        "--labels",
        type=Path,
        default=Path(__file__).with_name(LABEL_FILE_NAME),
        help=f"中文标签表，默认 {LABEL_FILE_NAME}",
    )
    ap.add_argument("--no-resign", action="store_true", help="只改文件，不重签名")
    ap.add_argument("--restore", action="store_true", help="从备份还原菜单渲染代码并重签名")
    args = ap.parse_args()

    if not args.patch_script_dir.is_dir():
        raise SystemExit(f"找不到补丁脚本目录：{args.patch_script_dir}")
    sys.path.insert(0, str(args.patch_script_dir))
    import patch_claude_zh_cn as p  # noqa: E402

    app: Path = args.app
    p.require_file(app / p.APP_ASAR_REL)
    labels = load_labels(args.labels)
    print(f"标签表：{args.labels}（{len(labels)} 条）")

    assets_dir = p.find_frontend_assets_dir(app)
    if assets_dir is None:
        raise SystemExit(f"找不到前端资源目录：{app/'Contents/Resources/ion-dist'}")

    if args.restore:
        print("1) 从备份还原菜单渲染代码……")
        changed = restore_frontend(assets_dir)
        if not changed:
            print("没有找到备份，无需还原。")
            return 0
    else:
        print("1) 修改菜单渲染代码……")
        changed = patch_frontend(assets_dir, labels)

    if changed is None:
        print("无需改动。")
        return 0

    if args.no_resign:
        print("2) 按 --no-resign 跳过重签名（应用重签名后才能正常启动）")
        return 0

    print("2) 重新签名应用（保持自动更新所需的 identifier DR）……")
    p.resign_app(app)
    print("完成。请退出并重新打开 Claude Desktop 查看效果。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
