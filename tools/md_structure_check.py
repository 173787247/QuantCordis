#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查 Markdown 的两种结构性损坏：围栏不配对 · 表格被跨行单元格打断。

## 为什么有它（2026-10-16）

这个仓有 24 个文档在 `docs/` 下，而此前**没有任何检查看它们的结构** ——
钩子只跑 smoke 与 privacy_check。两份坏掉的文档，读者会看到错误的渲染。

而发现它的路径值得记：我在另一个仓里造了两次样本想让同类检查失败、都失败，
**不猜、直接调那个函数**才证明样本没错 ⇒ 于是知道是**文件没被扫到** ⇒
把 `docs/` 加进扫描范围、立刻报出 5 处（3 真 2 误）。
⇒ 而这一条正是从那次推广过来的：**一个仓里的覆盖漏洞，另一个仓里大概率也有。**

## 判据

    · 围栏计数必须为偶（开头与结尾配对）
    · 一张表中间不该出现「不以 `|` 开头、但以 `|` 结尾」且后面 8 行内又有表格行的行

## 用法

    python tools/md_structure_check.py            # 扫根目录 + docs/
    python tools/md_structure_check.py <path...>  # 扫指定文件/目录
"""
from __future__ import annotations

import glob
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP_DIRS = ('third_party', '.git', 'node_modules', '__pycache__')


def _norm(x: str) -> str:
    t = x.lstrip()
    while t.startswith(">"):
        t = t[1:].lstrip()
    return t


def check_file(path: str):
    out = []
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").read().split("\n")
    except Exception as e:
        return [(-1, "读不出: %s" % str(e)[:70])]

    # ① 围栏必须成对
    fences = [k + 1 for k, l in enumerate(lines) if l.lstrip().startswith("```")]
    if len(fences) % 2:
        out.append((fences[-1], "围栏不配对（共 %d 个，应为偶数）⇒ 最后一个在 %d 行"
                    % (len(fences), fences[-1])))

    # ② 表格被跨行单元格打断
    in_fence = False
    for k, l in enumerate(lines):
        if l.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        t = _norm(l)
        if not t or t.startswith("|"):
            continue
        if t.endswith("|") and "|" in t:
            resumed = any(_norm(lines[x]).startswith("|")
                          for x in range(k + 1, min(k + 9, len(lines))))
            if resumed:
                out.append((k + 1, t[:90]))
    return out


def main() -> int:
    args = sys.argv[1:]
    if args:
        targets = []
        for a in args:
            if os.path.isdir(a):
                targets.extend(sorted(glob.glob(os.path.join(a, "**", "*.md"), recursive=True)))
            else:
                targets.extend(sorted(glob.glob(a)))
    else:
        targets = sorted({t for pat in ("*.md", os.path.join("docs", "*.md"))
                          for t in glob.glob(os.path.join(ROOT, pat))})
    total = 0
    checked = 0
    for p in targets:
        if not os.path.isfile(p) or any(d in p for d in SKIP_DIRS):
            continue
        checked += 1
        bad = check_file(p)
        if bad:
            total += len(bad)
            print("★ %s" % os.path.relpath(p, ROOT))
            for n, t in bad[:6]:
                print("     第 %d 行: %s" % (n, t))
    print("检查 %d 个 .md 文件 · 问题 %d 处 %s" % (
        checked, total, "✓" if total == 0 else "✗（围栏不配对 / 表格被打断）"))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
