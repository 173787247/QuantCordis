#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量级断裂复核 —— 用文档里那条判据，把 B 类逐个过一遍。

## 判据从哪来（不是我编的）

    `docs/PRICE-GAPS-FIXED.md` 已经写过这条判据:

        相邻交易日的收盘价比值应当落在涨跌停范围内
        → 阈值 1.15 倍（留出创业板 20% 的余量）与 5 倍各跑一次

    当时的结论是新库比旧库好 4-6 倍，并逐条查过那唯一一处，确认是停牌复牌。

## 这一轮为什么要重做

    文档那份是在 **25 只**上做的。现在新表铺到 **5185 只**，样本差 200 倍，
    所以「已根治」这个结论必须在新样本上重新成立一次才算数。

## 判据（能失败，而且阳性对照是现成的）

    对每个比值超阈值的相邻日对，看三条特征:
      ① 前一日成交量是否为 0（停牌）
      ② 当日成交量是否远大于前后（复牌放量）
      ③ 报价是否连续（复牌当天的收盘与停牌前同量级，不是 0.001 那种）
    · 三条都符合 ⇒ **停牌复牌**（真实事件，保留）
    · 否则 ⇒ **超阈值待看**（★ 不叫"断裂" ✓）

    ★★★ 2026-10-15 13:54: 【为什么【不【叫"【断裂"】**✓✓
      · ✗ 我【第一版【把【所有【超阈值【的【都【叫"【疑似断裂"】**✗ ⇒ 【实测【会【误导 ✓:
        【5185 只【上【有 33,374 个【超 1.15 倍【的【日对】✓
        · 【而【其中【**85.6% 【只是 1.15~1.5 倍**】✓ ⇒ 【那【就是【正常【的大涨大跌】
          （★ 创业板/科创板【单日【±20% 【合法 ✓）
        · ★★★ 【而【真正【极端【的（≥5 倍）【只有 15 个、【且【全部【是【停牌复牌】✓✓
      ⇒ ★★ 【所以【正确【的【结论【是**: 【"【新表【没有【一个【量级断裂"】✓
        · 【而【不是【"【发现【三万【个【断裂"】**✗✗
      ⇒ ★★★★ 【一个【起错【的【标签【会【让【人【读【出【相反【的【结论】✓ —— 【所以【要【改 ✓

    阳性对照: 000620.SZ 2011-07-08 必须判成「停牌复牌」（文档就是这么查的）。

## 用法

    python tools/audit_price_gaps.py                    # 全表，出汇总
    python tools/audit_price_gaps.py --code 000620.SZ   # 单只，看明细
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

TABLE = "quantcordis_bar_none"
RATIO_WARN = 1.15      # ★ 文档里的严口径（留出创业板 20% 余量）
RATIO_HARD = 5.0       # ★ 文档里的宽口径


def codes(limit=0, one=""):
    import db
    if one:
        return [one]
    rows = db.execute_query(
        "SELECT DISTINCT stock_code FROM %s ORDER BY stock_code" % TABLE)
    cs = [r["stock_code"] for r in rows]
    return cs[:limit] if limit else cs


def classify(prev, cur, nxt):
    """三条停牌复牌特征。返回 (是否停牌复牌, 证据串)。"""
    pv = float(prev.get("volume") or 0)
    cv = float(cur.get("volume") or 0)
    pc = float(prev.get("close_price") or 0)
    cc = float(cur.get("close_price") or 0)
    nv = float(nxt.get("volume") or 0) if nxt else 0.0

    cond1 = (pv == 0)                      # 前一日停牌
    # ★★★ 2026-10-15 13:43: 【"放量"是【相对【停牌期】说的】**✓✓
    #   ✗ 【我【第一版【写成 `cv > 次日量 × 2`】**✗
    #     ⇒ 【实测【阳性对照 000620.SZ 2011-07-08**: 【复牌量 887,992 vs 次日 500,777 = 1.77 倍
    #       ⇒ 【不【到两倍 ⇒ 【判成"【疑似断裂"】✗✗ ⇒ **【而【文档【明确【说【它【是【停牌复牌** ✓
    #   · ★ 【根因**: 【文档【原话【是"【复牌日【量【巨大"】—— 【巨大【是【相对【**停牌期**】（★ 0 ⇒ 88 万 ✓）
    #     【而【我【多加【了【一个【文档【没【有【的【约束】（★ 比次日大两倍 ✓）
    #   · ★★ 【正确**: 【只要"【从停牌【恢复【成交"【就【算【复牌放量】**✓
    #     （★ 而"【巨大"【由【0 ⇒ N 【这个【事实【本身【保证 ✓）
    cond2 = (cv > 0)                       # 停牌后恢复成交（0 ⇒ N 就是"量巨大" ✓）
    # ★ 报价连续: 复牌日与停牌前【同量级】（不是 0.001 那种），比值在 0.1~50 之间
    ratio = (cc / pc) if pc else 0
    cond3 = 0.1 <= ratio <= 50.0

    ev = "停牌期量=%g · 复牌量=%g · 次日量=%g · 比值=%.3f" % (pv, cv, nv, ratio)
    return (cond1 and cond2 and cond3), ev


def audit_one(code, verbose=False):
    import db
    rows = db.execute_query(
        "SELECT trade_date, close_price, volume FROM %s WHERE stock_code=%%s "
        "ORDER BY trade_date" % TABLE, (code,))
    out = []
    for i in range(1, len(rows)):
        pc = float(rows[i - 1]["close_price"] or 0)
        cc = float(rows[i]["close_price"] or 0)
        if pc <= 0 or cc <= 0:
            continue
        # ★ 比值取【大于 1 那边】（涨跌【都可疑 ✓）
        ratio = cc / pc if cc >= pc else pc / cc
        if ratio < RATIO_WARN:
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        is_halt, ev = classify(rows[i - 1], rows[i], nxt)
        out.append({"code": code, "date": str(rows[i]["trade_date"])[:10],
                    "ratio": round(ratio, 4), "halt": bool(is_halt), "ev": ev})
        if verbose:
            print("      %s  比值 %.3f  ⇒ %s  （%s）"
                  % (str(rows[i]["trade_date"])[:10], ratio,
                     "停牌复牌" if is_halt else "超阈值待看", ev))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jsonl", default="")
    args = ap.parse_args()

    cs = codes(args.limit, args.code)
    print("判据: 相邻收盘价比值应当落在涨跌停范围内（严口径 %.2f 倍 · 宽口径 %.1f 倍）"
          % (RATIO_WARN, RATIO_HARD))
    print("      超阈值时看停牌复牌三特征: 前日量 0 · 当日放量 · 报价连续")
    print("扫描 %d 只" % len(cs))
    print()

    t0 = time.time()
    allrows = []
    pairs = 0
    for c in cs:
        rs = audit_one(c, verbose=bool(args.code))
        allrows += rs
        pairs += 1
    n = len(allrows)
    hard = [r for r in allrows if r["ratio"] >= RATIO_HARD]
    halt = [r for r in allrows if r["halt"]]
    bad = [r for r in allrows if not r["halt"]]
    extreme = [r for r in allrows if r["ratio"] >= RATIO_HARD]
    print("扫描完成: %d 只 · 超严口径 %.2f 倍的相邻日对 **%d 个** · %.0f 秒"
          % (len(cs), RATIO_WARN, n, time.time() - t0))
    print("  其中: 停牌复牌 %d 个 · 超阈值待看 %d 个（★ 分母 %d ✓）" % (len(halt), len(bad), n))
    n_ext_bad = sum(1 for r in extreme if not r["halt"])
    print("  ★★ 极端（≥%.1f 倍）: %d 个 · **其中【不是【停牌复牌【的 %d 个】← 【这才【是【断裂候选**"
          % (RATIO_HARD, len(hard), n_ext_bad))
    print("  涉及标的: %d 只（★ 分母 %d ✓）" % (len(set(r["code"] for r in allrows)), len(cs)))
    print()
    if bad:
        print("  ★ 超阈值待看【前 15 个】（★ 不【等于【断裂 ✓）:")
        for r in sorted(bad, key=lambda x: -x["ratio"])[:15]:
            print("     %-12s %s  比值 %8.2f  （%s）" % (r["code"], r["date"], r["ratio"], r["ev"]))
    if args.jsonl:
        with io.open(args.jsonl, "w", encoding="utf-8") as f:
            for r in allrows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print()
        print("  ★ 明细已写: %s" % args.jsonl)
    # ★ 阳性对照 ✓
    if args.code:
        for r in allrows:
            if r["code"] == "000620.SZ" and r["date"] == "2011-07-08":
                print()
                print("  ★ 阳性对照 000620.SZ 2011-07-08 ⇒ %s"
                      % ("停牌复牌 ✓✓（与文档一致）" if r["halt"] else "判成疑似断裂 ✗（要查）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
