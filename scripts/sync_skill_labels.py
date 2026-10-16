#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描本机所有技能，把缺中文短标签/中文概要的自动翻译好、写回两张表，再重打菜单补丁。

用法
----
    python3 sync_skill_labels.py                 # 只扫描并报告缺哪些（不改任何东西）
    python3 sync_skill_labels.py --apply         # 翻译缺失项 + 写表 + 重打补丁 + 重签名
    python3 sync_skill_labels.py --apply --only 10x-team
                                                 # 只处理指定的技能（用来试探）

新增技能之后跑一次 `--apply`，菜单里的中文短名和悬浮气泡里的中文概要就都补上了。
翻译走你自己在 `~/.claude/settings.json` 里配的网关
（ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN），用的模型是
ANTHROPIC_DEFAULT_HAIKU_MODEL（默认 haiku，便宜快）。
技能名字和描述会发到那个网关——这是自动翻译绕不开的。

隐私提醒：如果某个技能的描述里有你不想外发的内容，把它写进
`.skip-translate`（每行一个技能名），它会保留英文、不打标签也不写概要。

产出（都只影响 Claude Desktop 的菜单显示，不改任何技能文件）
-----------------------------------------------------------
- `skill-labels.zh.json`  → 菜单里技能名字后面的中文短标签（名字后面那个 span）
- `skill-summaries.zh.json` → 悬浮气泡里中文概要（气泡原文上面的那一行）

两张表都由 localize_skill_menu.py 注入到渲染代码里，所以**不要**去改各技能的
SKILL.md：那是插件缓存、会被插件更新覆盖、改了还会进模型上下文，而且退不回来。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LABEL_PATH = SCRIPT_DIR / "skill-labels.zh.json"
SUMMARY_PATH = SCRIPT_DIR / "skill-summaries.zh.json"
SKIP_PATH = SCRIPT_DIR / ".skip-translate"
BATCH_SIZE = 10
DESC_CLIP = 500  # 描述送进模型前截断到这个长度
MAX_TOKENS = 16000  # 要留够额度：模型会先输出一大段 thinking，预算不够就没有 text 块

COMMENT = (
    "键 = 技能标识符（skillId 去掉插件前缀后的名字，或菜单里显示的名字），"
    "值 = 显示在技能名字后面的中文短标签。改完重跑 localize_skill_menu.py 即可。"
)
SUMMARY_COMMENT = (
    "键 = 技能标识符，值 = 中文概要；显示在 `/` 菜单的悬浮气泡里，"
    "排在英文原文上一行。本文件由 sync_skill_labels.py 自动维护。"
)

# 技能来源，顺序即优先级：同一个技能在多处出现时只认先扫到的那个。
SCAN_ROOTS: list[Path] = [
    Path.home() / ".claude/skills",
    Path.home() / ".claude/plugins/cache",
    Path.home() / "Library/Application Support/Claude-3p/local-agent-mode-sessions",
]

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


def parse_frontmatter(text: str) -> dict[str, str]:
    """从 SKILL.md 里取 name / description（不依赖 pyyaml）。"""
    match = FM_RE.match(text.lstrip("﻿"))
    if not match:
        return {}
    body = match.group(1)
    out: dict[str, str] = {}
    for key in ("name", "description"):
        # 值可能跨多行（折叠或引号包裹），取到下一个顶层键为止。
        hit = re.search(
            rf"^{key}[ \t]*:[ \t]*(.*?)(?=^[A-Za-z_][\w-]*[ \t]*:|\Z)",
            body,
            re.S | re.M,
        )
        if not hit:
            continue
        raw = hit.group(1).strip()
        if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
            raw = raw.replace('\\"', '"').replace("\\n", " ").replace("\\'", "'")
        out[key] = " ".join(raw.split())
    return out


def iter_skills() -> Iterator[tuple[str, Path, str]]:
    """按来源顺序遍历所有 SKILL.md，产出 (小写技能名, 路径, 英文描述)。

    同一个技能在多处出现时只认先扫到的那个（用户技能 > Claude Code 插件 > Desktop 缓存）。
    """
    seen: set[str] = set()
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_frontmatter(text)
            name = (fm.get("name") or skill_md.parent.name).strip().lower()
            if not name or name in seen:
                continue
            seen.add(name)
            yield name, skill_md, fm.get("description", "") or ""


def scan_skills() -> dict[str, str]:
    """扫描所有来源，返回 {技能名: 英文描述}。"""
    return {name: desc for name, _path, desc in iter_skills()}


def gateway() -> tuple[str, str, str]:
    """从 ~/.claude/settings.json 读网关配置（环境变量优先）。"""
    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model = os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "") or os.environ.get(
        "ANTHROPIC_MODEL", ""
    )
    settings = Path.home() / ".claude/settings.json"
    if settings.exists() and (not base or not token):
        env = json.loads(settings.read_text(encoding="utf-8")).get("env", {})
        base = base or env.get("ANTHROPIC_BASE_URL", "")
        token = token or env.get("ANTHROPIC_AUTH_TOKEN", "")
        model = model or env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "") or env.get(
            "ANTHROPIC_MODEL", ""
        )
    if not base or not token:
        raise SystemExit("读不到 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN，无法自动翻译。")
    return base.rstrip("/"), token, (model or "claude-haiku-4-5").strip()


PROMPT = """下面是一批 AI 技能（skill），每个有英文名和英文描述。
请为每个技能给出：
1. label：中文短标签，2-8 个汉字的名词短语，直接跟在技能名后面显示（例：PDF 处理、测试驱动开发）。不要标点、不要引号、不要「技能」二字。
2. summary：一句中文概要，20-45 个汉字，说明这个技能做什么、什么时候用。以句号结尾。

只输出 JSON 数组，不要任何解释或代码块标记。格式：
[{{"name":"<原样抄回英文名>","label":"<中文短标签>","summary":"<中文概要>"}}]

技能列表：
{items}"""


def call_gateway(base: str, token: str, model: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": token,
            "authorization": "Bearer " + token,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )


def extract_json_array(text: str) -> list[dict]:
    """从模型回复里抠出 JSON 数组（容忍代码块围栏和前后废话）。"""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < start:
        raise ValueError("回复里找不到 JSON 数组")
    return json.loads(text[start : end + 1])


def translate_batch(
    batch: list[str],
    descs: dict[str, str],
    base: str,
    token: str,
    model: str,
    result: dict[str, tuple[str, str]],
) -> None:
    """翻一批。解析不出来就把这批劈成两半再来（最小到单个）。"""
    if not batch:
        return
    items = "\n".join(f"- {n}：{(descs.get(n) or '(无描述)')[:DESC_CLIP]}" for n in batch)
    try:
        parsed = extract_json_array(call_gateway(base, token, model, PROMPT.format(items=items)))
    except (ValueError, json.JSONDecodeError) as exc:
        if len(batch) == 1:
            print(f"    [!] {batch[0]} 翻译失败（{exc}），下次重跑会再试")
            return
        print(f"    [·] 这批 {len(batch)} 条没解析出来，劈半重试")
        mid = len(batch) // 2
        translate_batch(batch[:mid], descs, base, token, model, result)
        translate_batch(batch[mid:], descs, base, token, model, result)
        return

    for entry in parsed:
        name = str(entry.get("name", "")).strip().lower()
        label = str(entry.get("label", "")).strip().strip("。，、\"'")
        summary = str(entry.get("summary", "")).strip()
        if name in batch and label:
            result[name] = (label, summary)


def translate(names: list[str], descs: dict[str, str], base: str, token: str, model: str):
    """分批翻译，返回 {技能名: (label, summary)}。"""
    result: dict[str, tuple[str, str]] = {}
    total = len(names)
    for i in range(0, total, BATCH_SIZE):
        batch = names[i : i + BATCH_SIZE]
        print(f"  翻译 {i + 1}-{i + len(batch)} / {total} ……", flush=True)
        translate_batch(batch, descs, base, token, model, result)
        for name in batch:
            if name in result:
                print(f"    {name} → {result[name][0]} ｜ {result[name][1]}")
    return result


def load_table(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        k: v
        for k, v in json.loads(path.read_text(encoding="utf-8")).items()
        if not k.startswith("_") and isinstance(v, str) and v
    }


def write_table(path: Path, comment: str, values: dict[str, str]) -> None:
    data = {"_comment": comment}
    data.update({k: values[k] for k in sorted(values)})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描全部技能，自动补齐中文短标签与概要")
    ap.add_argument("--apply", action="store_true", help="翻译缺失项并写入标签表（默认只报告）")
    ap.add_argument("--no-patch", action="store_true", help="只写表，不重打菜单补丁")
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="技能名",
        help="只处理这些技能（可重复），用来先试探一个",
    )
    args = ap.parse_args()

    skills = scan_skills()
    labels = load_table(LABEL_PATH)
    summaries = load_table(SUMMARY_PATH)
    skip = set()
    if SKIP_PATH.exists():
        skip = {
            line.strip().lower()
            for line in SKIP_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
    only = {n.strip().lower() for n in args.only}
    if only:
        skills = {n: d for n, d in skills.items() if n in only}
        print(f"按 --only 限定为：{', '.join(sorted(skills)) or '（一个都没匹配上）'}")

    need_label = sorted(n for n in skills if n not in labels and n not in skip)
    need_summary = sorted(n for n in skills if n not in summaries and n not in skip)
    missing = sorted(set(need_label) | set(need_summary))
    roots = sum(1 for r in SCAN_ROOTS if r.is_dir())
    print(f"扫到技能 {len(skills)} 个（来自 {roots} 个来源）")
    print(f"缺短标签 {len(need_label)} 个，缺概要 {len(need_summary)} 个")

    if missing:
        for name in missing:
            print(f"  - {name}")
    else:
        print("两张表都是最新的，不需要翻译。")

    if not args.apply:
        if missing:
            print("\n（这是预演，什么都没改。加 --apply 才会翻译并写入。）")
        return 0

    translated: dict[str, tuple[str, str]] = {}
    if missing:
        base, token, model = gateway()
        print(f"\n网关 {base}，模型 {model}，开始翻译……")
        try:
            translated = translate(missing, skills, base, token, model)
        except urllib.error.URLError as exc:
            raise SystemExit(f"网关连不上：{exc}")

    failed = [n for n in missing if n not in translated]
    for name, (label, summary) in translated.items():
        labels[name] = label
        if summary:
            summaries[name] = summary
    if translated:
        write_table(LABEL_PATH, COMMENT, labels)
        write_table(SUMMARY_PATH, SUMMARY_COMMENT, summaries)
        print(f"\n已写入 {LABEL_PATH}（{len(labels)} 条）")
        print(f"已写入 {SUMMARY_PATH}（{len(summaries)} 条）")
    if failed:
        print(f"[!] 这些没翻译成功，下次重跑会再试：{', '.join(failed)}")

    if args.no_patch or not translated:
        return 0

    print("\n重打菜单补丁……")
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "localize_skill_menu.py")], cwd=SCRIPT_DIR, check=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
