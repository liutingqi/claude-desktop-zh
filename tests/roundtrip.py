#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对着假 assets 目录跑往返测试，验证信任链改动没有破坏正常流程。

不碰真的 Claude.app，也不碰真的备份目录（backup_dir 全部显式传参）。
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import localize_skill_menu as L  # noqa: E402

LABELS = {"docx": "Word 文档"}
SUMMARIES = {"docx": "创建和编辑 Word 文档。"}
PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ← {detail}" if detail and not cond else ""))


def pristine(marker="v1"):
    """一段含两个锚点各一次、且不带补丁标记的假前端代码。"""
    return f"/*{marker}*/var a=1;{L.ANCHOR};let z=1,{L.DESC_ANCHOR}x=2;"


def setup():
    tmp = Path(tempfile.mkdtemp(prefix="zhskill-"))
    assets = tmp / "assets"
    assets.mkdir()
    target = assets / "chunk-fake.js"
    target.write_text(pristine(), encoding="utf-8")
    return tmp, assets, target, tmp / "backups"


def patched_ok(text):
    return (
        L.START in text and L.END in text and L.DESC_START in text and L.DESC_END in text
    )


def expect_exit(fn, tag):
    try:
        fn()
    except SystemExit as exc:
        print(f"        （预期退出）{exc}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"        非 SystemExit 的异常：{type(exc).__name__}: {exc}")
        return False
    return False


print("1) 首次打补丁 → 写入标记并备份原文")
tmp, assets, target, backups = setup()
orig = target.read_text(encoding="utf-8")
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
after1 = target.read_text(encoding="utf-8")
check("文件被改动", after1 != orig)
check("四处标记齐全", patched_ok(after1))
check("备份存在", (backups / target.name).exists())
check("备份内容 == 原文", (backups / target.name).read_text(encoding="utf-8") == orig)
import hashlib  # noqa: E402

check(
    "index.json 记下了原文 sha256",
    L.load_index(backups).get(target.name)
    == hashlib.sha256(orig.encode()).hexdigest(),
)
check(
    "备份目录权限 0700",
    stat.S_IMODE(os.stat(backups).st_mode) == 0o700,
    oct(stat.S_IMODE(os.stat(backups).st_mode)),
)

print("2) 再打一次 → 幂等跳过")
check("返回 None（跳过）", L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups) is None)
check("文件内容没变", target.read_text(encoding="utf-8") == after1)

print("3) --restore → 还原成原文")
ok = L.restore_frontend(assets, backup_dir=backups)
check("返回已还原", ok is True)
check("内容 == 原文", target.read_text(encoding="utf-8") == orig)

print("4) 备份被篡改 → 拒绝重打补丁")
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
(backups / target.name).write_text(orig + "/*注入*/", encoding="utf-8")
check(
    "sha256 不符时退出",
    expect_exit(
        lambda: L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups), "patch"
    ),
)

print("5) 备份被篡改 → 拒绝还原")
check(
    "sha256 不符时退出",
    expect_exit(lambda: L.restore_frontend(assets, backup_dir=backups), "restore"),
)

print("6) index.json 丢失 → 拒绝重打补丁（不猜）")
_, assets, target, backups = setup()
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
(backups / L.INDEX_NAME).unlink()
check(
    "无哈希记录时退出",
    expect_exit(
        lambda: L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups), "patch"
    ),
)

print("7) bundle 里是干净原文（升级后场景）→ 以它为准，不用历史备份")
_, assets, target, backups = setup()
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
newtext = pristine("v2-upgraded")
target.write_text(newtext, encoding="utf-8")
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
final = target.read_text(encoding="utf-8")
check("改的是新版原文", "v2-upgraded" in final and "v1" not in final)
check("新原文进了备份", (backups / target.name).read_text(encoding="utf-8") == newtext)

print("8) 迁移：仓库内旧备份目录（无哈希）→ 结构校验通过才接受")
_, assets, target, backups = setup()
legacy = tmp / "legacy-backups"
legacy.mkdir()
(legacy / target.name).write_text(orig, encoding="utf-8")
target.write_text(pristine("patched-live") + L.START + "x" + L.END, encoding="utf-8")
saved = L.LEGACY_BACKUP_DIR
L.LEGACY_BACKUP_DIR = legacy
try:
    print("8a) 不给 --trust-legacy-backup → 自动中止（钩子场景失败即安全）")
    check(
        "默认拒绝自动采用旧备份",
        expect_exit(
            lambda: L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups), "patch"
        ),
    )
    check("中止时没有改动 bundle", "patched-live" in target.read_text(encoding="utf-8"))

    print("8b) 显式信任 → 迁移")
    L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups, trust_legacy=True)
    migrated = target.read_text(encoding="utf-8")
    check("用的是旧备份（v1）而不是 bundle 里的残content", "var a=1;" in migrated)
    check("bundle 里那份已被丢弃", "patched-live" not in migrated)
    check("新备份已建", (backups / target.name).read_text(encoding="utf-8") == orig)

    print("9) 迁移：旧备份本身就是补丁后的内容 → 拒绝")
    _, assets2, target2, backups2 = setup()
    legacy2 = tmp / "legacy2"
    legacy2.mkdir()
    (legacy2 / target2.name).write_text(pristine("x") + L.START + "y" + L.END, encoding="utf-8")
    target2.write_text(pristine("patched-live") + L.START + "x" + L.END, encoding="utf-8")
    L.LEGACY_BACKUP_DIR = legacy2
    check(
        "含补丁标记的旧备份被拒绝",
        expect_exit(
            lambda: L.patch_frontend(
                assets2, LABELS, SUMMARIES, backup_dir=backups2, trust_legacy=True
            ),
            "patch",
        ),
    )

    print("10) 迁移：旧备份不像前端文件（锚点 0 次）→ 拒绝")
    _, assets3, target3, backups3 = setup()
    legacy3 = tmp / "legacy3"
    legacy3.mkdir()
    (legacy3 / target3.name).write_text("console.log('evil')", encoding="utf-8")
    target3.write_text(pristine("patched-live") + L.START + "x" + L.END, encoding="utf-8")
    L.LEGACY_BACKUP_DIR = legacy3
    check(
        "无锚点的旧备份被拒绝",
        expect_exit(
            lambda: L.patch_frontend(
                assets3, LABELS, SUMMARIES, backup_dir=backups3, trust_legacy=True
            ),
            "patch",
        ),
    )
finally:
    L.LEGACY_BACKUP_DIR = saved

print("11) 过期备份随升级清理，index 同步删除")
_, assets, target, backups = setup()
old = backups / "chunk-gone.js"
backups.mkdir(parents=True, exist_ok=True)
old.write_text(pristine(), encoding="utf-8")
L.store_backup(backups, old.name, pristine())
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
check("过期备份被删", not old.exists())
check("index 里也没有它了", old.name not in L.load_index(backups))
check("当前文件的记录还在", target.name in L.load_index(backups))

print("12) 旧位置残留同名文件 + 新位置有合法备份 → 走备份，不中止（真机踩过的顺序 bug）")
_, assets, target, backups = setup()
L.patch_frontend(assets, LABELS, SUMMARIES, backup_dir=backups)
real = L.LEGACY_BACKUP_DIR
stale_dir = tmp / "legacy-stale"
stale_dir.mkdir()
(stale_dir / target.name).write_text("console.log('stale')", encoding="utf-8")
L.LEGACY_BACKUP_DIR = stale_dir
try:
    # 换一套标签 → 内容不再是最新 → 强制走 read_original 重新取原文
    L.patch_frontend(assets, {"docx": "Word 文档 v2"}, SUMMARIES, backup_dir=backups)
    out = target.read_text(encoding="utf-8")
    check("有合法备份时不因旧位置残留而中止", patched_ok(out) and "v2" in out)
    check("原文取自合法备份，不是旧位置的残留", "var a=1;" in out and "stale" not in out)
finally:
    L.LEGACY_BACKUP_DIR = real

print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
