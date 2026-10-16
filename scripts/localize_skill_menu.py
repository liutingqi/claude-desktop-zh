#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Claude Desktop 的 `/` 菜单里，给技能名字后面加中文短标签、给悬浮气泡加中文概要。

背景
----
菜单行的渲染代码（`ion-dist/assets/v1/<hash>.js` 里的 SlashCommandMenuPopupBody）
只内联渲染「图标 + 名字 + 命中的别名 + 副标题」，技能描述 **只在鼠标悬浮的气泡里**。
所以想让中文出现在名字后面，必须给渲染代码插一行。

做法（只改渲染代码，绝不改技能 name / skillId）
------------------------------------------------
1. 找到含锚点 `className:"min-w-0 truncate",children:s(j,{text:t.label,...})` 的 JS 文件
   （全目录唯一，不写死哈希文件名，升级后仍可定位）。
2. 在该名字 span 之后插入一个条件渲染的 span（**短标签**），文本按以下顺序解析：
   a. `skill-labels.zh.json` 里以 skillId（去掉 `插件:` 前缀）为键的标签；
   b. 同一张表里以菜单显示名为键的标签；
   c. 兜底：该技能描述的第一行，若含中文且不超过 20 字符。
3. 在**同一个文件**里定位气泡的 description 取值点
   （`b=y?y.skillDescription:_&&"subtitle"in _?_.subtitle:void 0,`），把结果换成
   「中文概要 + 换行 + 英文原文」，概要取自 `skill-summaries.zh.json`。
   若原文首行已经含中文（内置技能的描述已被 localize_bundled_skills.py 处理过），
   则原样返回，避免中文叠两层。
4. ad-hoc 重签名整个 app（保持 identifier DR，自动更新仍可校验）。

**为什么不直接改各技能目录里的 SKILL.md？** 那种文件是插件缓存/技能实体，
改了会进模型上下文、会被插件更新覆盖、且没有备份就退不回来。渲染侧注入只影响
菜单显示，覆盖所有来源（内置 + 插件），升级后重跑即可。

注入块分别用 `/*zh-skill-label*/ … /*zh-skill-label-end*/` 和
`/*zh-skill-desc*/ … /*zh-skill-desc-end*/` 成对标记包住，
所以本脚本是**可重复执行**的：再跑一次会把整块换成新表，而不是跳过。

原始版本备份放在 `~/Library/Application Support/claude-desktop-zh/.app-backups/`——
**不能**放 bundle 里（会被 codesign 封进签名，之后删掉它就报
"a sealed resource is missing or invalid"），也**不**放技能目录里：备份会被原样写回
已签名的 app，其内容等于要执行的代码，属于可信输入，不该和会被同步/清理/分发的
仓库文件混在一起。备份带 sha256 记录，重打补丁和 `--restore` 前都会校验；
bundle 里的文件只要没打过补丁就优先拿它当原文（app 升级后正是这种情况），
从源头避免依赖历史备份。详见 `read_original`。

依赖
----
复用中文补丁脚本 https://github.com/javaht/claude-desktop-zh-cn （MIT）里的
asar 读写 / ElectronAsarIntegrity 更新 / 重签名逻辑。用 --patch-script-dir 指定其目录。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_PATCH_SCRIPT_DIR = Path("/Users/l/claude-desktop-zh-cn/scripts")
DEFAULT_APP = Path("/Applications/Claude.app")
LABEL_FILE_NAME = "skill-labels.zh.json"
SUMMARY_FILE_NAME = "skill-summaries.zh.json"

# 菜单行里「技能名字」那个 span 的唯一锚点（升级后若变，脚本会报错而不是乱改）。
# 末尾的 "})})" 是必须的：把整个 span 收尾包进来，插入的表达式才会落在
# 外层 children 数组元素之间，而不是掉进 span 的 props 对象里。
ANCHOR = (
    'className:"min-w-0 truncate",children:s(j,{text:t.label,'
    'query:v,highlightClassName:"font-semibold"})})'
)

# 悬浮气泡里 description 的取值点（同一个文件里的 SlashCommandMenuPopupBody 尾部）。
# 它是 `let ...,b=<这里>,x=...,...` 声明列表中的一项，所以替换结果必须仍是**单个表达式**：
# 不能新增 `b=...` 声明（`let` 声明列表里重复声明同名绑定会直接 SyntaxError），
# 也不能在新表达式里读写 b（b 此时还在 TDZ 里，会直接 ReferenceError）——
# 所以原表达式要作为**参数**整体传进去，整条替换成 `b=<新表达式>`。
DESC_ORIGINAL = 'y?y.skillDescription:_&&"subtitle"in _?_.subtitle:void 0'
DESC_ANCHOR = "b=" + DESC_ORIGINAL + ","

# 注入块的起止标记。成对标记让重复执行可以「整块替换」。
START = "/*zh-skill-label*/"
END = "/*zh-skill-label-end*/"
DESC_START = "/*zh-skill-desc*/"
DESC_END = "/*zh-skill-desc-end*/"
LEGACY_MARKER = "zh-skill-label"  # 旧版只有起始标记，用 in 判断即可覆盖新版
LEGACY_SUFFIX = ".bak-zh-skilllabel"  # 旧版把备份放在 bundle 内，已废弃

# 备份目录：两个「不能」——不能在 bundle 里（会被 codesign 封进签名），
# 也不能留在 git 仓库里。备份会被原样写回**已签名**的 app，其内容等于要执行的代码，
# 属于可信输入，不该和会被同步 / 清理 / 分发的仓库文件混在一处。改用用户私有目录。
BACKUP_DIR = Path.home() / "Library/Application Support/claude-desktop-zh/.app-backups"
# 早期版本用的位置（技能目录内的 .app-backups/）。只作为迁移来源读取，不再写入。
LEGACY_BACKUP_DIR = Path(__file__).resolve().parent.parent / ".app-backups"
# 备份的 sha256 记录；重打补丁与还原前都拿它确认备份没被改动过。
INDEX_NAME = "index.json"


def build_inject(labels: dict[str, str]) -> str:
    """生成插入菜单行的渲染表达式（一个自调用箭头函数）。

    - `_m` 是中文标签表，`_o` 是当前菜单项；
    - 外层包 `START` / `END` 标记，便于整块替换；
    - 注意 `"\\n"` 是 JS 字符串转义，必须保持字面反斜杠 n。
    """
    expr = (
        "((_m,_o)=>{"
        'let _k=(((_o.skillId||"")+"").split(":").pop()||"").trim().toLowerCase();'
        'let _v=_m[_k]||_m[(((_o.label||"")+"").trim().toLowerCase())]||"";'
        "if(!_v){"
        'let _f=(((_o.skillDescription||"")+"")||"").split("\\n")[0].trim();'
        '_v=_f.length<=20&&/[\\u4e00-\\u9fff]/.test(_f)?_f:""}'
        'return _v?s("span",{className:"ms-2 shrink-0 text-caption text-muted-as-secondary",'
        "children:_v}):null})(" + js_map(labels) + ",t)"
    )
    return "," + START + expr + END


def build_desc_inject(summaries: dict[str, str]) -> str:
    """生成替换气泡 description 取值点的表达式（整段替换 `DESC_ANCHOR`）。

    - 第一个参数 `_d` 是中文概要表，`_b` 是原本要显示的英文描述；
    - 描述首行已含中文时原样返回，避免把中文叠成两层
      （内置技能的描述已被 localize_bundled_skills.py 改成「中文摘要 + 英文原文」）；
    - 键的解析顺序与短标签一致：skillId 去前缀 → 菜单显示名；
    - `\\n` 同样是 JS 字符串转义，必须保持字面反斜杠 n。
    """
    expr = (
        "((_d,_b)=>{"
        'if(!_b||typeof _b!=="string")return _b;'
        'if(/[\\u4e00-\\u9fff]/.test(_b.split("\\n")[0]||""))return _b;'
        'let _k=((((_&&_.skillId)||"")+"").split(":").pop()||"").trim().toLowerCase();'
        'let _v=_d[_k]||_d[((((_&&_.label)||"")+"").trim().toLowerCase())]||"";'
        'return _v?_v+"\\n"+_b:_b'
        "})(" + js_map(summaries) + "," + DESC_ORIGINAL + ")"
    )
    return "b=" + DESC_START + expr + DESC_END + ","


def load_labels(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(k): str(v)
        for k, v in data.items()
        if not k.startswith("_") and isinstance(v, str) and v
    }


def js_map(labels: dict[str, str]) -> str:
    return json.dumps(labels, ensure_ascii=False, separators=(",", ":"))


def find_target(assets_dir: Path) -> Path:
    """在全部前端资源里按锚点定位菜单行渲染文件（不写死哈希文件名）。"""
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
    return hits[0]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_index(backup_dir: Path) -> dict[str, str]:
    """读备份的 sha256 记录；文件缺失或损坏时返回空表（当作「没有记录」处理）。"""
    path = backup_dir / INDEX_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_index(backup_dir: Path, index: dict[str, str]) -> None:
    path = backup_dir / INDEX_NAME
    body = json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(body, encoding="utf-8")


def accept_unverified(text: str, source: Path) -> str:
    """校验一份**没有 sha256 记录**的旧备份确实还像「未打补丁的原文」。

    旧版备份无法事后补哈希，所以退而求其次做结构校验：不含补丁标记、菜单行锚点
    恰好出现一次。过不了就直接退出——宁可不改，也不拿来路不明的内容去覆盖已签名的 app。

    **这是防手滑的合理性检查，不是安全边界**：攻击者要满足这两条毫无难度。
    真正的防线是「不自动信任」——见 `read_original` 里 `trust_legacy` 的说明。
    """
    if LEGACY_MARKER in text:
        raise SystemExit(f"{source} 已经是打过补丁的内容，不能当原文用，中止。")
    hits = text.count(ANCHOR)
    if hits != 1:
        raise SystemExit(
            f"{source} 里菜单行锚点出现 {hits} 次（应为 1），不像是 Claude 的前端文件，中止。"
        )
    return text


def store_backup(backup_dir: Path, name: str, text: str) -> None:
    """把原文写进备份目录并记录 sha256（内容没变就只补记录，不重复打印）。"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / name
    digest = sha256_text(text)
    if not backup.exists() or backup.read_text(encoding="utf-8") != text:
        backup.write_text(text, encoding="utf-8")
        print(f"  [备份] 原文 → {backup}")
    index = load_index(backup_dir)
    if index.get(name) != digest:
        index[name] = digest
        save_index(backup_dir, index)


def read_original(path: Path, backup_dir: Path, trust_legacy: bool = False) -> tuple[str, bool]:
    """取回未打补丁的原始内容，返回 (原始内容, bundle 是否被改动)。

    信任顺序（从高到低）：

    1. **bundle 里当前的文件**——只要它没打过补丁，它就是原文，比任何备份都可信
       （app 升级换了 chunk 内容之后就是这种情况）；
    2. `backup_dir` 里**带 sha256 记录且校验通过**的备份；
    3. 旧版遗留位置（技能目录的 `.app-backups/`、bundle 内的 `.bak-zh-skilllabel`）——
       没有哈希可查，因此**默认不信任**，只在显式传了 `trust_legacy=True` 时才采用，
       且仍要过 `accept_unverified` 的结构校验。

    第 3 条为什么不自动：那两处都在用户可写的范围内，而备份的最终去向是覆盖
    **已签名**的 app——等于把「能写我 home 目录」升级成「代码进了我信任的签名 app」，
    并且是持久的。更何况本脚本会从 SessionStart 钩子无人值守地跑：自动采用就等于
    静默安装。所以默认中止并打印候选的路径与哈希，由人确认后加
    `--trust-legacy-backup` 重跑（钩子场景下失败即安全）。
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    for private in (backup_dir.parent, backup_dir):
        try:
            private.chmod(0o700)  # 备份会成为 app 里要执行的代码，只给自己读写
        except OSError:
            pass

    dirty = False
    stray = path.with_name(path.name + LEGACY_SUFFIX)  # 旧版放在 bundle 内的备份
    live = path.read_text(encoding="utf-8")

    if LEGACY_MARKER not in live:
        # 没打过补丁 ⇒ 当前文件本身就是原文，顺手刷新备份，完全不碰历史备份。
        store_backup(backup_dir, path.name, live)
        if stray.exists():
            # 它是被 codesign 封住的资源，删掉就等于动了 bundle，必须重签名。
            stray.unlink()
            dirty = True
            print(f"  [清理] 删除 bundle 内旧备份 {stray.name}")
        return live, dirty

    # 已打过补丁：必须找到一份可信的原文。
    # 先查第 2 条（backup_dir 里带哈希记录的备份）——它是唯一被自动信任的来源。
    # 这一步必须排在旧位置候选**前面**：旧目录里往往还留着迁移前的同名副本，
    # 若反过来先看它，就会在新位置备份完全正常的情况下也无谓中止。
    backup = backup_dir / path.name
    expect = load_index(backup_dir).get(path.name)
    if backup.exists() and expect:
        text = backup.read_text(encoding="utf-8")
        if sha256_text(text) != expect:
            raise SystemExit(
                f"{backup} 的 sha256 校验不通过（备份被改动或损坏），"
                "拒绝用它重打补丁，中止。"
            )
        return text, False

    # 新位置没有可用备份，才轮到旧位置——默认不信任，见 docstring 第 3 条。
    legacy = [c for c in (stray, LEGACY_BACKUP_DIR / path.name) if c.exists()]
    if legacy and not trust_legacy:
        detail = "\n".join(
            f"      {c}\n"
            f"        sha256={sha256_text(c.read_text(encoding='utf-8'))}"
            for c in legacy
        )
        raise SystemExit(
            f"{path.name} 已打过补丁，但 {backup_dir} 里没有可校验的原文备份。\n"
            f"  在旧位置找到候选，但它们没有哈希记录，脚本不自动信任：\n{detail}\n"
            "  确认这些文件的来源可靠后，加 --trust-legacy-backup 重跑；\n"
            "  否则请先重装 Claude，再重打补丁。"
        )
    if legacy:
        source = legacy[0]
        text = accept_unverified(source.read_text(encoding="utf-8"), source)
        store_backup(backup_dir, path.name, text)
        if source == stray:
            stray.unlink()
            dirty = True
        print(f"  [迁移] 原文备份 {source} → {backup_dir / path.name}")
        return text, dirty

    # 既没有可校验的备份，也没有旧位置候选：明确说清是缺文件还是缺记录，不猜。
    if not backup.exists():
        raise SystemExit(
            f"{path.name} 已打过补丁，但在 {backup} 找不到原始备份，无法安全重打。"
        )
    raise SystemExit(
        f"{backup} 没有可校验的 sha256 记录（{INDEX_NAME} 缺失或未收录它），"
        "无法确认备份没被改动，拒绝用它重打补丁，中止。"
    )


def prune_stale_backups(assets_dir: Path, backup_dir: Path) -> None:
    """清理两类无用备份：bundle 内的旧备份、以及原文件已消失（app 已升级）的备份。"""
    for legacy in sorted(assets_dir.glob("*" + LEGACY_SUFFIX)):
        legacy.unlink()
        print(f"  [清理] 删除 bundle 内旧备份 {legacy.name}")
    if not backup_dir.exists():
        return
    live = {p.name for p in assets_dir.glob("*.js")}
    index = load_index(backup_dir)
    for backup in sorted(backup_dir.iterdir()):
        if backup.name == INDEX_NAME or backup.name in live:
            continue
        backup.unlink()
        index.pop(backup.name, None)
        print(f"  [清理] 删除过期备份 {backup.name}（原文件已随升级消失）")
    save_index(backup_dir, index)


def strip_blocks(text: str) -> str:
    """去掉所有已注入的标记块，把文件还原成「只差待注入内容」的状态。

    备份理论上永远是注入前的原文，这里只是多一道保险：万一备份本身来自
    旧版脚本注入之后，也不会把老标签叠在新标签前面。
    """
    for start, end in ((START, END), (DESC_START, DESC_END)):
        while start in text and end in text:
            i = text.index(start)
            j = text.index(end, i) + len(end)
            text = text[:i] + text[j:]
    return text


def patch_frontend(
    assets_dir: Path,
    labels: dict[str, str],
    summaries: dict[str, str],
    backup_dir: Path = BACKUP_DIR,
    trust_legacy: bool = False,
) -> Path | None:
    path = find_target(assets_dir)
    original, dirty = read_original(path, backup_dir, trust_legacy)

    for name, anchor in (("短标签", ANCHOR), ("气泡概要", DESC_ANCHOR)):
        if original.count(anchor) != 1:
            raise SystemExit(
                f"{name}锚点在 {path.name} 中出现 {original.count(anchor)} 次，中止。"
            )

    prune_stale_backups(assets_dir, backup_dir)
    base = strip_blocks(original)
    patched = base.replace(ANCHOR, ANCHOR + build_inject(labels), 1)
    patched = patched.replace(DESC_ANCHOR, build_desc_inject(summaries), 1)
    current = path.read_text(encoding="utf-8")
    if current == patched and not dirty:
        print(
            f"  [跳过] {path.name} 的中文标签（{len(labels)} 条）"
            f"与中文概要（{len(summaries)} 条）都已是最新"
        )
        return None

    path.write_text(patched, encoding="utf-8")
    print(f"  [ok] {path.name}：已写入中文标签 {len(labels)} 条、中文概要 {len(summaries)} 条")
    print(f"       原始备份：{backup_dir / path.name}")
    return path


def restore_frontend(assets_dir: Path, backup_dir: Path = BACKUP_DIR) -> bool:
    """把菜单渲染代码还原成插入前的版本（从 bundle 外的备份）。

    还原同样是「拿备份覆盖已签名的 app」，所以先用 sha256 确认备份没被动过，
    再确认它确实还像个原始前端文件，两条都过了才写。
    """
    if not backup_dir.exists():
        return False
    live = {p.name for p in assets_dir.glob("*.js")}
    index = load_index(backup_dir)
    restored = False
    for backup in sorted(backup_dir.iterdir()):
        if backup.name == INDEX_NAME or backup.name not in live:
            continue
        text = backup.read_text(encoding="utf-8")
        expect = index.get(backup.name)
        if not expect or sha256_text(text) != expect:
            raise SystemExit(
                f"{backup} 的 sha256 校验不通过（备份被改动或损坏），"
                "拒绝用它覆盖已签名的 app，中止。"
            )
        accept_unverified(text, backup)
        (assets_dir / backup.name).write_text(text, encoding="utf-8")
        print(f"  [ok] 已还原 {backup.name}")
        restored = True
    for legacy in sorted(assets_dir.glob("*" + LEGACY_SUFFIX)):
        legacy.unlink()
        restored = True
    return restored


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
    ap.add_argument(
        "--summaries",
        type=Path,
        default=Path(__file__).with_name(SUMMARY_FILE_NAME),
        help=f"中文概要表（悬浮气泡用），默认 {SUMMARY_FILE_NAME}",
    )
    ap.add_argument("--no-resign", action="store_true", help="只改文件，不重签名")
    ap.add_argument(
        "--trust-legacy-backup",
        action="store_true",
        help="把旧位置（技能目录内 / bundle 内）没有哈希记录的备份当作原文。"
        "仅在确认过它的来源时使用；默认不信任，会中止并打印候选路径与哈希。",
    )
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
    summaries = (
        load_labels(args.summaries) if args.summaries.exists() else {}
    )
    print(f"概要表：{args.summaries}（{len(summaries)} 条）")

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
        changed = patch_frontend(
            assets_dir, labels, summaries, trust_legacy=args.trust_legacy_backup
        )

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
