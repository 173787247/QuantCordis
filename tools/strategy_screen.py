#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略筛选：在整张可回测表上跑一组策略，按三条判据给结论。

判据（三条同时成立才算「有超额」，任一条不成立就如实报找不到）
    ① 均值超额 > 0
    ② 中位超额 > 0
    ③ 为正只数 > 50%

    为什么是三条而不是一条：均值会被少数极端值主导。此前实测里，
    某个策略均值负十一、中位正九点一七、十一只里十一只为正 —— 只报均值会把分布的形状说反。

口径
    超额 = 策略收益 − 同期买入持有（两者同口径，后复权）
    费率：佣金万二点五双边 + 卖出印花税千分之零点五（回测器自带，ETF 免印花税）
    成交：信号在 K_i 收盘出，用 K_{i+1} 开盘成交

样本
    `quantcordis_bar_none` 里全部有数据的标的（不筛选，不挑好看的）。

续跑
    结果逐条追加到 outputs/screen_<label>.jsonl；重跑时已有的 (code, strategy) 直接跳过。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

DEFAULT_STRATEGIES = ["grid_classic", "boll_revert", "bias_revert",
                      "macd_1d", "ma20_hold", "turtle_donchian"]


def codes():
    import db
    rows = db.execute_query(
        "SELECT DISTINCT stock_code FROM quantcordis_bar_none ORDER BY stock_code")
    return [r["stock_code"] for r in rows]


def load_done(path):
    done = set()
    if os.path.isfile(path):
        for line in io.open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                done.add((o.get("code"), o.get("strategy")))
            except Exception:
                continue
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default=",".join(DEFAULT_STRATEGIES))
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0, help="最多几只（0 = 全部）")
    # ★★★ 2026-10-15 13:55: 【抽样参数】**✓✓
    #   · 【为什么要它**: 【上次筛选【用的是【干净池【每 5 取 1【的 1056 只 ✓
    #     ⇒ ★ 【这次【要【用【一个【**不【与它【重叠**】的【样本【做【复现 ✓
    #       （★ 若【同一策略【在两个【独立【样本上【都【成立 ⇒ 【证据【强【一档 ✓）
    #   · ★ 【用法**: `--step 5 --offset 2` ⇒ 【从第 2 只【起【每 5 取 1 ✓
    #     ⇒ 【与【上次【的 0,5,10… 【错开【成 2,7,12… ⇒ 【不重叠 ✓✓
    ap.add_argument("--step", type=int, default=1, help="每 step 只取 1（默认 1 = 不抽）")
    ap.add_argument("--offset", type=int, default=0, help="从第几只开始（默认 0）")
    # ★★★ 2026-10-15 13:56: 【显式【排除【已筛过【的【代码】**✓✓
    #   · 【为什么【不【靠 step/offset】✗: 【上次【的样本【取自【干净池【排序【后的【列表 ✓
    #     【而【现在【列表【是【新表【的【超集、【排序【位置【会【移】✗
    #       ⇒ ★ 【"offset 2"【不【保证【与【上次【不重叠 ✓
    #   · ★★ 【所以【要【显式【排除】，【并【且【数【出【交集【来【验它【真的【不重叠 ✓
    ap.add_argument("--exclude-from", default="",
                    help="读一个 jsonl，把它里面出现过的 code 全部排除")
    ap.add_argument("--label", default="default")
    ap.add_argument("--slip", type=float, default=0.0,
                    help="单边比例滑点（如 0.001 = 0.1%%）。回测默认 0，"
                         "而 0 会让「每只交易几十次」的策略看起来比实际好")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    cs = codes()
    if args.step and args.step > 1:
        cs = cs[args.offset::args.step]      # ★ 抽样 ✓
    elif args.offset:
        cs = cs[args.offset:]
    if args.exclude_from and os.path.isfile(args.exclude_from):
        import json as _j
        _ex = set()
        for _l in io.open(args.exclude_from, encoding="utf-8", errors="replace"):
            _l = _l.strip()
            if not _l:
                continue
            try:
                _ex.add(_j.loads(_l).get("code"))
            except Exception:
                pass
        _before = len(cs)
        cs = [c for c in cs if c not in _ex]
        print("★ 已排除【上次筛过的 %d 只】⇒ 样本 %d ⇒ **%d**（★ 交集应为 0 ✓）"
              % (len(_ex), _before, len(cs)))
    if args.limit:
        cs = cs[:args.limit]
    out_dir = os.path.join(ROOT, "outputs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "screen_%s.jsonl" % args.label)

    print("策略 %d 个: %s" % (len(strategies), ", ".join(strategies)))
    print("样本 %d 只（quantcordis_bar_none · step=%d offset=%d）· %s → %s"
          % (len(cs), args.step, args.offset, args.start, args.end))
    print("判据: 均值超额>0 且 中位超额>0 且 为正只数>50%")
    print("滑点: 单边 %.3f%%" % (args.slip * 100))
    print("结果追加到 %s" % out)
    if args.dry_run:
        return 0

    from backtest.engine import run_backtest

    done = load_done(out)
    # ★★★ 2026-10-15 01:30: 【票优先【而不是【策略优先】**✓✓
    #   · ★ 引擎【有【进程内缓存】: 「同一只票多个策略只加载一次」（★ 原注释 ✓）
    #   · ✗ 策略优先 ⇒ 【每一只【都是【新票 ⇒ 【缓存【全不命中】✗
    #     ⇒ 【实测**: 每只【都【付【一次【冷加载（★ 10 秒级 ✓）
    #   · ✓ 票优先 ⇒ 【同一只票的 6 个策略【共享【一次加载】✓
    #     · ★★ 实测【同一只票**: 第 1 个策略 14.47 秒【而【第 2、3 个 **0.16 / 0.34 秒**✓✓
    #   · ★★★ 而且【部分结果【更【有意义】: 【"前 N 只票 × 全部 6 个策略"】
    #     ⇒ 【那【就是【一个【完整【的【小实验】，【统计量【直接【可算 ✓✓
    jobs = [(c, s) for c in cs for s in strategies if (c, s) not in done]
    print("待跑 %d 个（已完成 %d）· 并发 %d" % (len(jobs), len(done), args.workers))
    print(flush=True)

    lock = io.open(out, "a", encoding="utf-8")
    t0 = time.time()
    n_ok = n_err = 0

    def one(job):
        code, strat = job
        try:
            r = run_backtest(code, strat, args.start, args.end, slippage=args.slip)
            return {"code": code, "strategy": strat,
                    "excess": r.get("excess"), "ret": r.get("total_return"),
                    "bh": r.get("buy_hold"), "trades": r.get("trades"),
                    # ★★★ 2026-10-15 14:33: 【暴露【也【记下来】**✓✓
                    #   · 【为什么**: 【换【指数【基准【后【还【剩【一个【混淆】—— 【指数【满仓【而
                    #     【策略【会【空仓 ⇒ 【实测 grid_classic 只【在【场 55.5%】· ma20_hold **45.5%**】
                    #     ⇒ ★ 【不【记【暴露【就【没【法【把【指数【折算【成【同样【暴露【的一份 ✓
                    "exposure": r.get("exposure"),
                    "days_in_market": r.get("days_in_market")}
        except Exception as e:
            return {"code": code, "strategy": strat,
                    "error": "%s: %s" % (type(e).__name__, str(e)[:90])}

    with ThreadPoolExecutor(max_workers=max(1, min(2, args.workers))) as ex:
        for i, res in enumerate(ex.map(one, jobs), 1):
            lock.write(json.dumps(res, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                lock.flush()
            if res.get("error"):
                n_err += 1
            else:
                n_ok += 1
            if i % 200 == 0:
                el = time.time() - t0
                rest = (len(jobs) - i) * (el / max(1, i))
                print("  %d/%d · ok %d · err %d · %.0f 秒 · 预计还需 %.0f 分钟"
                      % (i, len(jobs), n_ok, n_err, el, rest / 60.0), flush=True)
    lock.flush()
    lock.close()
    print("完成: ok %d · err %d · %.0f 秒" % (n_ok, n_err, time.time() - t0))
    return summarize(out, strategies)


def summarize(path, strategies):
    rows = []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    print()
    print("=" * 86)
    print("策略筛选 · %s" % path)
    print("判据: 均值超额>0 且 中位超额>0 且 为正只数>50%")
    print("=" * 86)
    print("%-18s %10s %10s %10s %9s %9s" % ("策略", "均值超额", "中位超额", "为正只数", "均交易", "样本"))
    winners = []
    for s in strategies:
        exs = sorted(float(r["excess"]) for r in rows
                     if r.get("strategy") == s and r.get("excess") is not None)
        trs = [float(r.get("trades") or 0) for r in rows
               if r.get("strategy") == s and r.get("excess") is not None]
        if not exs:
            print("%-18s %10s" % (s, "（无数据）"))
            continue
        mean = sum(exs) / len(exs)
        med = statistics.median(exs)
        pos = sum(1 for x in exs if x > 0)
        c1, c2, c3 = mean > 0, med > 0, pos > len(exs) / 2
        mark = "  <= 三条都过" if (c1 and c2 and c3) else ""
        if c1 and c2 and c3:
            winners.append(s)
        print("%-18s %+9.2f%% %+9.2f%% %5d/%-4d %9.1f %9d%s"
              % (s, mean, med, pos, len(exs),
                 (sum(trs) / len(trs)) if trs else 0.0, len(exs), mark))
        print("%-18s   ①均值%s ②中位%s ③为正过半%s"
              % ("", "过" if c1 else "不过", "过" if c2 else "不过", "过" if c3 else "不过"))
    print()
    if winners:
        print("结论: 三条都过的策略 = %s" % ", ".join(winners))
    else:
        print("结论: 【找不到】三条都过的策略 —— 如实报告，不挑好看的数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
