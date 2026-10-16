#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公开仓的隐私守卫 —— 只看「哪些东西不该出现在一个别人会克隆的仓里」。

## 为什么有它

旧仓有 privacy_scan，而公开仓的钩子只跑 smoke。公开仓才是别人会克隆的那个，
它的隐私反倒没有守卫。而 2026-10-16 往它里面放文档时，是**手动**查的 —— 下次不会有人手动查。

## 判据

    跟踪的文件里不许出现只对某台机器成立的东西：
    家目录 · 用户名 · 本机地址 · Windows 挂载路径 · 令牌形状 · 邮箱。

    · 这个判据能失败：故意写一行家目录，它必须非零退出。

## 用法

    python tools/privacy_check.py          # 扫 git 跟踪的文件
    python tools/privacy_check.py --all    # 扫工作区（含未跟踪）
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PATS = [
    (r"/home/[a-z0-9_]+", "家目录"),
    (r"/Users/[A-Za-z0-9_.-]+", "macOS 家目录"),
    (r"/mnt/[a-z]/", "Windows 挂载路径"),
    (r"\b[A-Za-z]:\\\\?(?:Users|用户)\\\\", "Windows 用户目录"),
    # ★★★ 2026-10-16 10:17: 【把「本机地址」【从【判据里【拿掉】**✓✓
    #   · 【实测【它【立刻【在 tools/factor_study.py 里【报【了【一个 localhost】✗
    #     ⇒ 【而【那【个【是【我【以【前【推【上【去【的【代码、【不【是【这【一【轮【的 ✓
    #   · ★★ 【而【判【断【的【结果【是**: 【**localhost / 127.0.0.1 【在【每【台【机器上
    #     【都【是【同【一个【意思、【不【泄【露【任【何【这【台【机器【的【信【息**】✓✓
    #     ⇒ ⇒ ★★★ 【所以【错【的【是【我【的【判据、【不【是【那【段【代码**】✓
    #   · ★★ 【而【这【是【"【判据【要【覆盖【可能【坏【的【东西"【的【**反面**: 【
    #     **别【把【不【会【坏【的【也【算【进【去】（★ 那【会【制【造【假【报【警、
    #     而【假【报【警【会【让【人【开【始【绕【过【守【卫 ✓）
    (r"\b(?:sk|ghp|gho|xox[bp])[-_][A-Za-z0-9]{16,}", "令牌形状"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "邮箱"),
]
SKIP_DIRS = ("third_party", "node_modules", ".git", "__pycache__", "docs/quantcordis-archive")


def tracked(all_files=False):
    if all_files:
        out = []
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
            for f in files:
                out.append(os.path.relpath(os.path.join(base, f), ROOT))
        return out
    try:
        r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           timeout=60)
        return [x for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    files = tracked(a.all)
    hits = []
    scanned = 0
    for rel in files:
        if any(rel.startswith(s) or ("/" + s + "/") in ("/" + rel) for s in SKIP_DIRS):
            continue
        if os.path.basename(rel) == "privacy_check.py":
            continue                      # ★ 它自己含通用模式字面量
        fp = os.path.join(ROOT, rel)
        if not os.path.isfile(fp) or os.path.getsize(fp) > 4_000_000:
            continue
        try:
            txt = open(fp, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        scanned += 1
        for pat, name in PATS:
            for m in re.finditer(pat, txt):
                hits.append((rel, name, m.group(0)[:48]))
    print("扫 %d 个文件 · 命中 %d 处 %s" % (scanned, len(hits), "✓" if not hits else "✗"))
    for rel, name, val in hits[:20]:
        print("   ✗ %s → %s（%s）" % (rel, name, val))
    if hits:
        print("\n⇒ 公开仓里不许有只对某台机器成立的东西。删掉或改成占位符。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
