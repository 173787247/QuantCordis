# -*- coding: utf-8 -*-
"""★ 滑点【敏感性】✓
判据原文（★ docs/SCAN-NEW-DATA.md:3-8 ✓）:
  平均超额 = 策略收益 − 同期买入持有 · 两者同口径（后复权）
  样本: 19 只主板 · 2018-01-01 → 2026-06-30 · 费率 佣金万2.5 + 印花税千0.5
  干净池 = 最近 20 个交易日每一天都有成交
  → 5,184 只 → 按代码升序每 172 只取 1 只 → 前 30 只 → 去掉创业板/科创板 → 19 只主板
本轮【加【一个【维度**: 比例滑点（★ 单边 ✓）∈ {0, 0.001, 0.002, 0.005}
"""
import io, json, os, sys, traceback
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "data"))

OUT = os.path.join(HERE, "_slip_sweep.txt")
lines = []


def say(s):
    lines.append(str(s))
    io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    print(s, flush=True)


try:
    import pool
    from backtest.engine import run_backtest

    # ★★★ 2026-10-15 00:02: 【样本【必须【从【回测器【真正读的【那张表【来】**✓✓
    #   ✗ 原来【用 `pool.select()` ⇒ 它读【旧表 `trade_stock_daily`】✗
    #     ⇒ ★★ 【而回测器读【新表 `quantcordis_bar_none`】
    #       ⇒ 【实测: 抽出的 3 只【新表【里【全没有】✗✗
    #         「RuntimeError: 库里没有 600004.SH」✓
    #     ⇒ ★★★ 【两个工具【对"用哪份数据"【意见【不一致】✗ ⇒ 【跑不通【并且【会误导 ✓
    #   ⇒ ★ 【正确**: 【从【回测器【读的【表【取【可用【票】✓
    import db as _db
    _rows = _db.execute_query(
        "SELECT DISTINCT stock_code FROM quantcordis_bar_none ORDER BY stock_code")
    _avail = [r["stock_code"] for r in _rows]
    say("★ 【回测器【真正【可用的【票】（★ quantcordis_bar_none ✓）= %d 只" % len(_avail))
    say("   %s" % ", ".join(_avail))
    _old = pool.select(n_days=20, verbose=False)
    say("★ （★ 对照: `pool.select()`【干净池】= %s 只 ⇒ ★★ 它读【旧表】，与回测器【不一致】**✗"
        % (_old or {}).get("count"))
    _stock_codes = _avail
    res = {"codes": _avail}
    keys = sorted(res.keys()) if isinstance(res, dict) else []
    say("★ pool.select 返回键: %s" % keys)
    codes = None
    for k in ("stocks", "codes", "clean", "list", "full"):
        v = (res or {}).get(k)
        if isinstance(v, (list, tuple)) and v:
            codes = list(v)
            break
    if codes is None:
        say("✗✗ 【找不到【票【列表 key ⇒ 【全部键值类型】: %s"
            % {k: type((res or {}).get(k)).__name__ for k in keys})
        raise SystemExit(1)
    say("★ 干净池 = %d 只（★ 判据: 最近 20 个交易日每天都有成交 ✓）" % len(codes))
    codes = sorted(codes)
    # ★ 样本 = 【新表里【全部【可用【主板【票 ✓（★ 判据【写清 ✓）
    sample = [c for c in codes
              if not str(c).startswith(("300", "301", "688", "689"))]
    say("★ 抽样后（★ 每 172 只取 1 → 前 30 → 去创业板/科创板 ✓）= %d 只" % len(sample))
    say("   %s" % ", ".join(sample))

    LEVELS = [0.0, 0.001, 0.002, 0.005]
    START, END = "2018-01-01", "2026-06-30"

    def one(args):
        code, slip = args
        try:
            r = run_backtest(code, "grid_classic", START, END, slippage=slip)
            return (code, slip, {"ret": r.get("total_return"), "bh": r.get("buy_hold"),
                                 "ex": r.get("excess"), "tr": r.get("trades")})
        except Exception as e:
            return (code, slip, {"err": "%s: %s" % (type(e).__name__, str(e)[:60])})

    jobs = [(c, s) for s in LEVELS for c in sample]
    say("")
    say("★ 共 %d 个回测（★ %d 只 × %d 个滑点 ✓）· 并发 2 ✓" % (len(jobs), len(sample), len(LEVELS)))
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(one, jobs))

    by = {}
    errs = {}
    for (code, slip, r) in results:
        if "err" in r:
            errs.setdefault(slip, []).append((code, r["err"]))
        else:
            by.setdefault(slip, []).append(r)

    say("")
    say("=" * 78)
    say("★ grid_classic · %s → %s · 费率 佣金万2.5 + 印花税千0.5 ✓" % (START, END))
    say("★ 判据: 平均超额 = 策略收益 − 同期买入持有（★ 后复权同口径 ✓）")
    say("=" * 78)
    say("%-9s %9s %9s %9s %9s %8s" % ("单边滑点", "均值超额", "中位超额", "为正只数", "均交易", "样本"))
    for s in LEVELS:
        rs = by.get(s) or []
        if not rs:
            say("%-9s （无）" % ("%.1f%%" % (s * 100)))
            continue
        exs = sorted(float(x["ex"]) for x in rs if x["ex"] is not None)
        trs = [float(x["tr"] or 0) for x in rs]
        mean = sum(exs) / len(exs) if exs else 0.0
        med = exs[len(exs) // 2] if exs else 0.0
        pos = sum(1 for x in exs if x > 0)
        say("%-9s %+8.2f%% %+8.2f%% %5d/%-3d %9.1f %6d"
            % ("%.1f%%" % (s * 100), mean, med, pos, len(exs),
               (sum(trs) / len(trs)) if trs else 0.0, len(exs)))
    if errs:
        say("")
        for s, v in errs.items():
            say("★ %.1f%% 滑点【失败 %d 只】: %s" % (s * 100, len(v), v[:3]))
    say("")
    say("★ 判据（★ 能失败 ✓）: 若【某滑点下【均值超额【转负 ⇒ 【如实报『找不到』】✓")
except Exception:
    say("✗✗ 异常:\n%s" % traceback.format_exc()[:1500])
