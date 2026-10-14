#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""滑点敏感性：策略超额在多小的滑点下消失。

判据
    平均超额 = 策略收益 − 同期买入持有（两者同口径 · 后复权）
    样本: 库里全部可回测标的（quantcordis_bar_none 的 DISTINCT stock_code）
    费率: 佣金万2.5（双边）+ 印花税千0.5（卖出 · ETF 免）—— 与 backtest/engine.py 同一常量

判据能失败
    若某个滑点下均值超额转负，就如实报告找不到。

用法
    # 策略函数不在本仓时，用环境变量指向含 lib/strategy_registry.py 的目录
    export QUANTCORDIS_STRATEGY_ROOT=<目录>
    python tools/slippage_sweep.py --strategy grid_classic \
        --start 2018-01-01 --end 2026-06-30 --slip 0 0.001 0.002 0.005
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))


def available_codes():
    """回测器真正读的那张表里有哪些标的。"""
    import db
    rows = db.execute_query(
        "SELECT DISTINCT stock_code FROM quantcordis_bar_none ORDER BY stock_code")
    return [r["stock_code"] for r in rows]


def stock_only(codes):
    """去掉创业板与科创板（300/301/688/689）。"""
    return [c for c in codes if not str(c).startswith(("300", "301", "688", "689"))]


def sweep(strategy, start, end, levels, codes, workers=2):
    from backtest.engine import run_backtest

    def one(args):
        code, slip = args
        try:
            r = run_backtest(code, strategy, start, end, slippage=slip)
            return (code, slip, {"ex": r.get("excess"), "tr": r.get("trades")}, None)
        except Exception as e:
            return (code, slip, None, "%s: %s" % (type(e).__name__, str(e)[:70]))

    jobs = [(c, s) for s in levels for c in codes]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, jobs))


def summarize(results, levels):
    out = []
    for s in levels:
        rs = [r[2] for r in results if r[1] == s and r[2]]
        errs = [(r[0], r[3]) for r in results if r[1] == s and r[3]]
        if not rs:
            out.append((s, None, None, None, None, 0, errs))
            continue
        exs = sorted(float(x["ex"]) for x in rs if x["ex"] is not None)
        trs = [float(x["tr"] or 0) for x in rs]
        out.append((s,
                    sum(exs) / len(exs) if exs else 0.0,
                    exs[len(exs) // 2] if exs else 0.0,
                    sum(1 for x in exs if x > 0),
                    (sum(trs) / len(trs)) if trs else 0.0,
                    len(exs), errs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="grid_classic")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--slip", type=float, nargs="+", default=[0.0, 0.001, 0.002, 0.005])
    ap.add_argument("--workers", type=int, default=2, help="并发（不要调大）")
    ap.add_argument("--all", action="store_true", help="含创业板/科创板")
    args = ap.parse_args()

    levels = list(args.slip)
    codes = available_codes()
    if not args.all:
        codes = stock_only(codes)
    print("策略 %s · %s → %s · 样本 %d 只" % (args.strategy, args.start, args.end, len(codes)))
    print("费率 佣金万2.5（双边）+ 印花税千0.5（卖出 · ETF 免）")
    print("判据 平均超额 = 策略收益 − 同期买入持有（后复权同口径）")
    print("共 %d 个回测 · 并发 %d" % (len(codes) * len(levels), args.workers))
    print()
    print("%-9s %10s %10s %9s %9s %6s"
          % ("单边滑点", "均值超额", "中位超额", "为正只数", "均交易", "样本"))
    for (s, mean, med, pos, tr, n, errs) in summarize(sweep(
            args.strategy, args.start, args.end, levels, codes, args.workers), levels):
        if mean is None:
            print("%-9s （无有效样本）" % ("%.1f%%" % (s * 100)))
            continue
        print("%-9s %+9.2f%% %+9.2f%% %5d/%-3d %9.1f %6d"
              % ("%.1f%%" % (s * 100), mean, med, pos, n, tr, n))
        for (c, e) in errs[:3]:
            print("     失败 %s: %s" % (c, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
