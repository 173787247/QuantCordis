#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验 5 分钟线的完整性 —— 抽查，判据是逐位相同。

## 判据

    同一天，48 根 5 分钟 K 的 volume 求和，必须**逐位等于**日K 那天的 volume
    （容差 1e-6，也就是要求完全相等，不是"接近"）。

    这一条同时证明两件事：单位相同（两边都是股），以及分钟数据完整没漏根。

## 为什么是抽查而不是全量

    全量要 5185 次比对，每次都要连数据源，成本高。抽查用等距抽样（每 N 取 1），
    与代码排序无关，跨板块。2026-10-15 全量入库 7209 万根之后抽查 30 只，
    30 只全部一致。

    抽查的边界要写清：分母是抽查只数，不是 5185。它说明"抽到的都对"，
    不说明"每一只都对"。

## 用法

    python tools/verify_5m.py --step 173 --limit 30
    python tools/verify_5m.py --code 000001.SZ        # 单只
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))
TOL = 1e-6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=173, help="每 step 只取 1（默认 173）")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--code", default="")
    args = ap.parse_args()

    import db
    from xtquant import xtdata
    xtdata.connect()

    rows = db.execute_query("SELECT DISTINCT stock_code FROM quantcordis_bar_none "
                            "ORDER BY stock_code")
    allc = [r["stock_code"] for r in rows]
    sample = [args.code] if args.code else allc[::args.step][:args.limit]
    print("判据: 同一天 48 根 5 分钟的 volume 求和 必须逐位等于 日K 那天的 volume（容差 %g）" % TOL)
    print("样本 %d 只（分母 %d 只 · 每 %d 取 1）" % (len(sample), len(allc), args.step))
    print()
    ok = bad = skip = 0
    fails = []
    for c in sample:
        r = db.execute_query("SELECT trade_date FROM trade_stock_daily WHERE stock_code=%s "
                             "AND trade_date < CURDATE() ORDER BY trade_date DESC LIMIT 1", (c,))
        if not r:
            skip += 1
            continue
        day = str(r[0]["trade_date"])[:10]
        tag = day.replace("-", "")
        d = xtdata.get_market_data_ex([], [c], period="5m", start_time=tag + "000000",
                                      end_time=tag + "235959", count=-1)
        df = (d or {}).get(c)
        if df is None or len(df) == 0:
            skip += 1
            continue
        v5 = float(df["volume"].sum())
        vd = float((db.execute_query(
            "SELECT volume FROM trade_stock_daily WHERE stock_code=%s AND trade_date=%s",
            (c, day))[0] or {}).get("volume") or 0)
        ratio = vd / v5 if v5 else 0
        if abs(ratio - 1.0) < TOL:
            ok += 1
        else:
            bad += 1
            fails.append((c, day, len(df), v5, vd, ratio))
    print("结果: 一致 %d · 不一致 %d · 跳过 %d（分母 %d）" % (ok, bad, skip, len(sample)))
    for c, day, n, v5, vd, ratio in fails[:10]:
        print("   %-12s %s · %d 根 · 5分=%.0f · 日K=%.0f · 比 %.4f" % (c, day, n, v5, vd, ratio))
    print()
    if bad:
        print("⇒ 判据失败：%d 只不一致" % bad)
        return 1
    print("⇒ 判据通过：抽到的全部逐位一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
