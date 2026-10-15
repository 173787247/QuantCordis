#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找「因子表漏了除权事件」的日子 —— 复权口径的体检。

## 为什么有它（2026-10-15 的一次真实发现）

    金标准（复权不改变收益率）在 600519.SH 上报了 3 天不对，文件头把它们都记成
    「连续两次除权的边界 → 多乘了一次」。逐天查之后发现归因错了:

      · 2006-05-19 与 2006-05-24 **是**除权日，而数据源给的 preClose **等于**前一天 close
        ⇒ 那两天数据源的昨收**没做除权调整** ⇒ 金标准的分母是错的，复权本身是对的
      · 2006-05-25 **不是**除权日，而 close 从 91.410 跳到 39.590（1:1 送转）
        ⇒ **除权事件表里没有这一条** ⇒ 复权把送转当成了 −56.69% 的暴跌
      · 关键证据: 那天数据源给的 preClose = 44.970，**它是调整过的**
        ⇒ 数据源自己知道那天除权，**而它的因子表里没有**

    所以三类日子要分开: ① 真漏事件（危险）② 数据源昨收没调整（金标准的边界，不是 bug）
    ③ 正常。

## 判据（能失败，而且有阳性对照）

    对每一天:
      · 若 `preClose == 前一天 close` ⇒ 数据源的昨收没调整 ⇒ **那天比不了，跳过**
      · 否则（数据源调整过）⇒ 比对 复权序列的收益 与 close/preClose−1 的收益
        · 不一致 ⇒ **因子表漏了当天的除权事件**，并可由 `prev_close / preClose` 反推 dr

    阳性对照: 600519.SH 的 2006-05-25 必须被找出来（实测会）。

## 用法

    python tools/audit_adjust_gaps.py --code 600519.SH        # 单只，看明细
    python tools/audit_adjust_gaps.py --limit 200             # 扫一批，出汇总
    python tools/audit_adjust_gaps.py --limit 200 --fix       # 把反推出来的事件补进因子表
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

TOL = 1e-6


def codes(limit=0, one=""):
    import db
    if one:
        return [one]
    rows = db.execute_query(
        "SELECT DISTINCT stock_code FROM quantcordis_bar_none ORDER BY stock_code")
    cs = [r["stock_code"] for r in rows]
    return cs[:limit] if limit else cs


def audit_one(code, verbose=False):
    """返回 (缺口列表, 跳过天数, 总天数)。缺口元素: (日期, dr反推, 复权收益, none收益)。"""
    import db
    import adjust as A
    rows = db.execute_query(
        "SELECT trade_date, close_price, pre_close FROM quantcordis_bar_none "
        "WHERE stock_code=%s ORDER BY trade_date", (code,))
    if len(rows) < 3:
        return [], 0, 0
    dates = [str(r["trade_date"])[:10] for r in rows]
    closes = [float(r["close_price"] or 0) for r in rows]
    pres = [float(r["pre_close"] or 0) for r in rows]
    ev = A._read_divid(code)
    back = A.back_adjust(dates, closes, ev)

    gaps, skipped = [], 0
    for i in range(1, len(dates)):
        pc, cl, pcv = pres[i], closes[i], closes[i - 1]
        if pc <= 0 or cl <= 0 or pcv <= 0:
            continue
        if abs(pc - pcv) < 1e-9:
            # ★ 数据源的昨收【没做除权调整】⇒ 那天【金标准的两个口径【本来就【不可比 ✓
            skipped += 1
            continue
        r_none = cl / pc - 1.0
        r_adj = (back[i] / back[i - 1] - 1.0) if back[i - 1] else 0.0
        if abs(r_adj - r_none) > TOL:
            dr = pcv / pc          # ★ 由 preClose 反推的因子 ✓
            gaps.append((dates[i], dr, r_adj, r_none))
            if verbose:
                print("      %s  dr推=%.6f  复权=%+.4f%%  none=%+.4f%%  差=%+.4f%%"
                      % (dates[i], dr, r_adj * 100, r_none * 100, (r_adj - r_none) * 100))
    return gaps, skipped, len(dates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="", help="只查一只")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--fix", action="store_true",
                    help="把反推出来的事件补进 quantcordis_divid（source=preClose_proxy）")
    args = ap.parse_args()

    cs = codes(args.limit, args.code)
    print("判据: 数据源 preClose 调整过的日子里，复权收益必须等于 close/preClose−1")
    print("      （preClose 等于前一天 close 的日子说明数据源没调整 ⇒ 比不了，跳过）")
    print("扫描 %d 只" % len(cs))
    print()

    t0 = time.time()
    n_gap = n_skip = n_days = 0
    hit_stocks = []
    fixes = []
    for c in cs:
        gaps, skipped, nd = audit_one(c, verbose=bool(args.code))
        n_gap += len(gaps)
        n_skip += skipped
        n_days += nd
        if gaps:
            hit_stocks.append((c, len(gaps), gaps[0]))
            fixes += [(c, d, dr) for (d, dr, _a, _b) in gaps]
            if not args.code:
                print("   %-12s 缺口 %2d 天 · 最早 %s（复权 %+.2f%% vs none %+.2f%%）"
                      % (c, len(gaps), gaps[0][0], gaps[0][2] * 100, gaps[0][3] * 100))
    print()
    print("扫描完成: %d 只 · %d 个交易日 · 缺口 %d 天 · 跳过（昨收未调整）%d 天 · %.0f 秒"
          % (len(cs), n_days, n_gap, n_skip, time.time() - t0))
    print("有缺口的标的: %d 只" % len(hit_stocks))

    if args.fix and fixes:
        import adjust as A
        by = {}
        for (c, d, dr) in fixes:
            by.setdefault(c, []).append((d, dr))
        n = 0
        for c, evs in by.items():
            A._store_divid(c, evs, source="preClose_proxy")
            n += len(evs)
        print()
        print("已补进因子表: %d 条（%d 只）· source=preClose_proxy ⇒ 可追溯" % (n, len(by)))
    elif fixes:
        print()
        print("⇒ 加 --fix 可把反推出来的 dr 补进因子表（source=preClose_proxy）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
