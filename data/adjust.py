# -*- coding: utf-8 -*-
"""QuantCordis 复权计算 —— 自己算，不依赖数据源的复权口径

## 公式

    dr = 前收 ÷ 除权参考价（数据源 get_divid_factors 的 dr 列）
      · 验算: 茅台 2026-06-26 分红 28.02423 元
        1212.10 ÷ (1212.10 − 28.02423) = 1.023671
        而分红表给的 dr = 1.023663 → 吻合到 5 位
      · 送转也成立: 2006 年每股转增 1 股 → dr = 2.006365 → 股本翻倍价格腰斩

    后复权(t) = none(t) × Π(dr for ed <= t) ← 以最早为基准
    前复权(t) = none(t) × Π(1/dr for ed > t) ← 以最新为基准
    两种视图从同一份 none 数据算出 → 一套数据两种视图

## 判据（金标准: 复权不改变收益率）

    用 none + 数据源的 preClose 算的日收益
      应当 == 用复权价算的日收益

    → 这个判据不依赖任何外部复权序列 → 不会被坏数据污染
    → 实测（茅台 2001-2026 · 6,092 个可比日）: 对上 6,089 · 不对 3**

    剩下 3 个:
      · 2006-05-19 与 2006-05-24: none 收益为 0（preClose == close）→ 无真实交易 → 无法验证
      · 2006-05-25: 连续两次除权（相隔 5 天）的边界 → 多乘了一次 dr
        → 已知边界情形，尚未处理

## 为什么不直接用数据源的 front（实测）

    茅台 6,093 天里，xtdata 的 front 有 3,631 天是断点（59.6%）
    判据: front ≤ 0，或与前/后 5 日内任一合理值的比值 >2 或 <0.5
    直观例（2016-07）: none=293.90 合理 · 而 front=2.2428
    → 自己算比数据源给的更可信 不只是"可复现"

## 用法

    python adjust.py --code 600519.SH --verify # 金标准自检（能失败）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from db import execute_query # noqa: E402

TZ = _dt.timezone(_dt.timedelta(hours=8)) # 北京时间（UTC 会差一天 实测过）

TABLE = "quantcordis_bar_none"


def norm_date(s):
    """ 统一日期格式 → '20020725' 与 '2002-07-25' 都变成 '2002-07-25'

     为什么必须有它（实测的坑）:
      分红表的日期是 '2002-07-25'
      而日K 的日期（str(index)[:10]）是 '20020725'
      → 字符串比较永远不相等 → 因子从来没更新过
      → 症状: 金标准显示29 天不对，而且全在除权日
      → 修格式后: 29 → 3**
    """
    s = str(s)[:10].replace("-", "")
    if len(s) >= 8:
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:8])
    return str(s)[:10]


def get_divid_events(code):
    """从 xtdata 取除权事件 → [(日期, dr)] 日期统一格式 """
    from xtquant import xtdata
    dv = xtdata.get_divid_factors(code)
    if dv is None or len(dv) == 0:
        return []
    ev = []
    for i in range(len(dv)):
        r = dv.iloc[i]
        d = _dt.datetime.fromtimestamp(int(r["time"]) / 1000, TZ).strftime("%Y-%m-%d")
        ev.append((norm_date(d), float(r["dr"])))
    ev.sort()
    return ev


def fetch_none(code):
    """从库里取不复权日K → (dates, closes, precloses) """
    rows = execute_query(
        "SELECT trade_date, close_price, pre_close FROM %s "
        "WHERE stock_code=%%s ORDER BY trade_date" % TABLE, (code,))
    dates, closes, pres = [], [], []
    for r in rows:
        dates.append(norm_date(r["trade_date"]))
        closes.append(float(r["close_price"]))
        pres.append(float(r["pre_close"]) if r["pre_close"] is not None else None)
    return dates, closes, pres


def back_adjust(dates, closes, events):
    """后复权（以最早为基准）: none × Π(dr for ed <= t) """
    evset = {d: dr for d, dr in events}
    out, f = [], 1.0
    for i, d in enumerate(dates):
        if d in evset and evset[d] > 0:
            f *= evset[d]
        out.append(closes[i] * f)
    return out


def front_adjust(dates, closes, events):
    """前复权（以最新为基准）: none × Π(1/dr for ed > t) """
    out = []
    for i, d in enumerate(dates):
        g = 1.0
        for (ed, dr) in events:
            if ed > d and dr > 0:
                g /= dr
        out.append(closes[i] * g)
    return out


def verify(code, tol=0.0005):
    """ 金标准: 复权不改变收益率 → 返回 (通过?, 明细) """
    dates, closes, pres = fetch_none(code)
    if not dates:
        return False, {"错误": "库里没有 %s 的数据（先跑 bar_none.py）" % code}
    events = get_divid_events(code)
    back = back_adjust(dates, closes, events)
    ok = bad = 0
    worst = 0.0
    wd = ""
    bads = []
    for i in range(1, len(dates)):
        if pres[i] is None or pres[i] <= 0 or closes[i] <= 0 or back[i-1] <= 0:
            continue
        e = abs((closes[i] / pres[i] - 1) - (back[i] / back[i-1] - 1))
        if e < tol:
            ok += 1
        else:
            bad += 1
            if e > worst:
                worst, wd = e, dates[i]
            bads.append((dates[i], e))
    return (bad == 0), {"对上": ok, "不对": bad, "最大差": worst,
                        "最差日": wd, "不对的日子": bads[:8],
                        "除权次数": len(events), "总天数": len(dates)}


def main():
    ap = argparse.ArgumentParser(description="QuantCordis 复权计算与自检")
    ap.add_argument("--code", required=True)
    ap.add_argument("--verify", action="store_true", help=" 金标准自检（能失败）")
    args = ap.parse_args()

    if args.verify:
        ok, info = verify(args.code)
        print(" %s 复权自检（金标准: 收益不变）" % args.code)
        for k in ("对上", "不对", "最大差", "最差日", "总天数", "除权次数"):
            if k in info:
                print(" %-10s %s" % (k, info[k]))
        if info.get("不对的日子"):
            print(" 不对的日子:", info["不对的日子"])
        if "错误" in info:
            print(" %s" % info["错误"])
        print(" → %s" % (" 全部通过" if ok else " 有不对 → 见上面明细"))
        return 0 if ok else 1

    dates, closes, pres = fetch_none(args.code)
    events = get_divid_events(args.code)
    back = back_adjust(dates, closes, events)
    front = front_adjust(dates, closes, events)
    print(" %s · %d 天 · %d 次除权" % (args.code, len(dates), len(events)))
    for i in range(0, len(dates), max(1, len(dates) // 6)):
        print(" %s none=%-11.4f 后复权=%-13.4f 前复权=%-11.4f" % (
            dates[i], closes[i], back[i], front[i]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
