#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前自检：语法、可导入性、文档链接一致性。

三项检查，任一不过就退出码 1：

  ① 语法：所有 .py 必须能被 compile()（不只是能被解析）
  ② 可导入：不依赖行情源的模块必须能 import
     · 依赖 xtquant 的模块（需要 miniQMT 客户端）标记为 SKIP，不算失败
     · 其他任何异常都算失败
  ③ 文档：README 里点名的 docs/*.md 必须都存在

用法：
    python tools/smoke.py
"""
from __future__ import annotations

import io
import os
import py_compile
import re
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 需要行情源（xtquant）才能导入的模块；其余模块必须干净导入
NEEDS_XTQUANT = {"data/bar_none.py"}


def py_files():
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in (".git", "__pycache__", ".venv", "venv")]
        for f in fn:
            if f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(dp, f), ROOT))
    return sorted(out)


def check_syntax(files):
    bad = []
    for rel in files:
        try:
            py_compile.compile(os.path.join(ROOT, rel), doraise=True, cfile="/tmp/_smoke.pyc")
        except Exception as e:
            bad.append((rel, str(e).splitlines()[-1][:90]))
    return bad


def check_imports(files):
    ok, skipped, bad = [], [], []
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + os.path.join(ROOT, "data")
    env["PYTHONIOENCODING"] = "utf-8"
    for rel in files:
        if rel in NEEDS_XTQUANT:
            skipped.append((rel, "需要 xtquant（miniQMT 客户端）"))
            continue
        mod = rel[:-3].replace(os.sep, ".")
        try:
            r = subprocess.run([sys.executable, "-c", "import " + mod],
                               cwd=ROOT, capture_output=True, timeout=120, env=env)
            if r.returncode == 0:
                ok.append(rel)
                continue
            err = (r.stderr or b"").decode("utf-8", "replace")
            if "xtquant" in err:
                skipped.append((rel, "需要 xtquant"))
            else:
                bad.append((rel, err.strip().splitlines()[-1][:90]))
        except subprocess.TimeoutExpired:
            bad.append((rel, "导入超时"))
    return ok, skipped, bad


def check_docs_index():
    """README 里点名的 docs/<name>.md 必须存在。"""
    readme = io.open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    named = set(re.findall(r"([A-Z][A-Z0-9-]+\.md)", readme))
    missing = sorted(n for n in named
                     if not os.path.isfile(os.path.join(ROOT, "docs", n))
                     and n != "README.md")
    return missing


def main():
    files = py_files()
    print("=" * 72)
    print("发布前自检 · %d 个 .py" % len(files))
    print("=" * 72)

    bad_syn = check_syntax(files)
    print("① 语法: %s" % ("通过" if not bad_syn else "失败 %d" % len(bad_syn)))
    for (rel, msg) in bad_syn:
        print("     %s: %s" % (rel, msg))

    ok, skipped, bad_imp = check_imports(files)
    print("② 可导入: %d 通过 · %d 跳过 · %s"
          % (len(ok), len(skipped), "0 失败" if not bad_imp else "%d 失败" % len(bad_imp)))
    for (rel, why) in skipped:
        print("     跳过 %s（%s）" % (rel, why))
    for (rel, msg) in bad_imp:
        print("     失败 %s: %s" % (rel, msg))

    missing = check_docs_index()
    print("③ 文档索引: %s" % ("全部存在" if not missing else "缺 %s" % missing))

    fail = bool(bad_syn or bad_imp or missing)
    print()
    print("结论: %s" % ("失败" if fail else "通过"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
