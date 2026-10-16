#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Claude Desktop 内置技能（docx/pdf/pptx/xlsx/…）的描述加上中文摘要。

菜单和悬浮提示里显示的英文副标题来自 `app.asar` 内的
`resources/bundled-skills/manifest.json`，改插件缓存（cowork_plugins/cache）无效。

只改 `description`，**绝不改 `name`**：name 是技能标识符，既要参与 skillId
（`bundled:docx`）和 `${name}.skill` 的文件查找，也会出现在系统提示里。

`description` 会被改写成「中文摘要 + 换行 + 英文原文」，保留完整英文触发信息。
重复执行是幂等的。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PATCH_SCRIPT_DIR = Path("/Users/l/claude-desktop-zh-cn/scripts")
DEFAULT_APP = Path("/Applications/Claude.app")
TARGET = "resources/bundled-skills/manifest.json"
SUMMARY_FILE_NAME = "bundled-skills.zh.json"


def load_summaries(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(k): str(v)
        for k, v in data.items()
        if not k.startswith("_") and isinstance(v, str) and v
    }


def strip_known_prefixes(description: str, prefixes: list[str]) -> str:
    """去掉历史上已经加过的中文摘要，拿到原始英文正文。"""
    for prefix in prefixes:
        marker = prefix + "\n"
        while description.startswith(marker):
            description = description[len(marker) :]
    return description


def main() -> int:
    ap = argparse.ArgumentParser(description="给内置技能描述加中文摘要")
    ap.add_argument("--app", type=Path, default=DEFAULT_APP)
    ap.add_argument(
        "--patch-script-dir",
        type=Path,
        default=DEFAULT_PATCH_SCRIPT_DIR,
        help="claude-desktop-zh-cn 的 scripts 目录（提供 asar 读写与重签名）",
    )
    ap.add_argument(
        "--summaries",
        type=Path,
        default=Path(__file__).with_name(SUMMARY_FILE_NAME),
        help=f"中文摘要表，默认 {SUMMARY_FILE_NAME}",
    )
    ap.add_argument("--no-resign", action="store_true", help="只改文件，不重签名")
    args = ap.parse_args()

    if not args.patch_script_dir.is_dir():
        raise SystemExit(f"找不到补丁脚本目录：{args.patch_script_dir}")
    sys.path.insert(0, str(args.patch_script_dir))
    import patch_claude_zh_cn as p  # noqa: E402

    app: Path = args.app
    asar = app / p.APP_ASAR_REL
    p.require_file(asar)

    summaries = load_summaries(args.summaries)
    print(f"摘要表：{args.summaries}（{len(summaries)} 条）")

    data = asar.read_bytes()
    header_size, _header_string, header = p.read_asar_header(data, asar)
    entry = p.get_asar_file_entry(header, TARGET)
    manifest = json.loads(p.read_asar_entry_content(data, header_size, entry, TARGET).decode("utf-8"))

    changed = 0
    for skill in manifest.get("skills", []):
        name = skill.get("name")
        summary = summaries.get(name)
        if not summary:
            continue
        original = strip_known_prefixes(skill.get("description", ""), list(summaries.values()))
        new_description = f"{summary}\n{original}"
        if skill.get("description") == new_description:
            print(f"  [跳过] {name} 已是中文摘要 + 英文原文")
            continue
        skill["description"] = new_description
        changed += 1
        print(f"  [ok] {name}")

    if not changed:
        print("没有需要改的描述，未写入。")
        return 0

    new_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    applied = p.replace_asar_file_content(app, TARGET, new_bytes)
    print(f"asar 替换：{'已写入' if applied else '内容未变化（跳过）'}")
    if applied and not args.no_resign:
        print("重新签名应用……")
        p.resign_app(app)
        print("完成。请重启 Claude Desktop。")
    elif applied:
        print("按 --no-resign 跳过重签名（应用重签名后才能正常启动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
