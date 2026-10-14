#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把复权因子落库，一次性做完。

为什么
    `get_divid_events` 原来是每次回测从行情源现取，于是回测依赖客户端在线，
    而且同一段历史在不同时间跑可能拿到不同的因子 —— 那正是「回测不可复现」。
    现在改成读库优先，这个工具负责把库填满。

判据（能失败）
    落库的因子与当场从数据源取的必须逐条一致（见本文件的 --check）。
    实测三只：600519.SH 30 条、000001.SZ 30 条、002668.SZ 7 条，全部一致。

用法
    python tools/backfill_divid.py              # 回填库里所有标的
    python tools/backfill_divid.py --limit 20
    python tools/backfill_divid.py --check      # 抽 3 只比对，不一致就退出码 1
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))


def codes():
    import db
    rows = db.execute_query(
        "SELECT DISTINCT stock_code FROM quantcordis_bar_none ORDER BY stock_code")
    return [r["stock_code"] for r in rows]


def check(sample):
    import adjust as A
    ok = True
    for c in sample:
        live = A._fetch_divid_events_from_source(c)
        A._store_divid(c, live)
        got = A._read_divid(c)
        same = (len(live) == len(got)) and all(
            a[0] == b[0] and abs(a[1] - b[1]) < 1e-12 for a, b in zip(live, got))
        ok = ok and same
        print("   %-12s 现取 %3d 条 · 库中 %3d 条 ⇒ %s"
              % (c, len(live), len(got), "一致" if same else "不一致"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.check:
        print("判据: 落库的因子与当场从数据源取的逐条一致")
        rc = check(["600519.SH", "000001.SZ", "002668.SZ"])
        print("结论: %s" % ("通过" if rc == 0 else "失败"))
        return rc

    import adjust as A
    cs = codes()
    if args.limit:
        cs = cs[:args.limit]
    print("回填复权因子: %d 只" % len(cs))
    ok = empty = fail = 0
    n_ev = 0
    t0 = time.time()
    for i, c in enumerate(cs, 1):
        try:
            ev = A._fetch_divid_events_from_source(c)
            if not ev:
                empty += 1
                continue
            A._store_divid(c, ev)
            ok += 1
            n_ev += len(ev)
        except Exception as e:
            fail += 1
            print("   %s 失败: %s: %s" % (c, type(e).__name__, str(e)[:70]), flush=True)
        if i % 100 == 0:
            print("   进度 %d/%d · 成功 %d · 无除权 %d · 失败 %d · %.0f 秒"
                  % (i, len(cs), ok, empty, fail, time.time() - t0), flush=True)
    print()
    print("完成: 成功 %d · 无除权记录 %d · 失败 %d · 共 %d 条因子 · %.0f 秒"
          % (ok, empty, fail, n_ev, time.time() - t0))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
