# -*- coding: utf-8 -*-
"""干净股票池 —— 只做一件事: 给出可以拿来回测的股票清单

## 为什么
    库里有两类标的会让回测结论失真:
      ① 已退市 / 长期停牌 —— 数据源里只剩占位 0，任何复权口径都救不了
         实测 4 只（000627 · 000040 · 000622 · 000005）在 xtdata 的 none 口径下
         也是全 0，2026 年查不到任何数据，即已退市
      ② 价格量级断裂 —— 正常交易的大票也可能有，不是退市造成的
         实测 54 只带病在池（美的 · 格力 · 五粮液 · 招行 …）
         那是复权算错，只能靠自己算复权根治

## 判据（两条，都能失败）
    ① 最近 N 个交易日每一天都有成交
       volume > 0 且 close_price > 0（N 默认 20，约一个月）
    ② 不在排除名单里
       默认排除所有区间都有断裂的那 7 只，它们无法靠缩短区间规避

## 用法
    python pool.py
    python pool.py --json
    python pool.py --check 600519.SH
    python pool.py --out /tmp/pool.txt
## 退出码
    0 = 正常且池子非空 · 1 = 池子为空或参数错（判据能失败）

## 数据归属
只读 trade_stock_daily，不写任何东西
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

# 不硬编码路径 → 从本文件的位置推导
# 为什么（有实测）
# · 硬编码路径 → Windows 的 Python 看不懂 WSL 风格的路径
# → 报 No module named '...'
# · → 从 __file__ 推导 → 既没有硬编码，也不存在路径形式转换问题
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from db import execute_query # noqa: E402

DEFAULT_EXCLUDE = [
    "300029.SZ", "600193.SH", "605081.SH", "600421.SH",
    "300344.SZ", "600355.SH", "600636.SH",
]


def _q(sql, args=None):
    """ 走 QuantCordis 自己的连接（data/db.py）"""
    return execute_query(sql, args)


def recent_days(n):
    rows = _q("select distinct trade_date d from trade_stock_daily "
              "order by trade_date desc limit %s", (n,))
    return [str(x["d"])[:10] for x in rows]


def select(n_days=20, exclude=None, verbose=True):
    days = recent_days(n_days)
    if len(days) < n_days:
        raise RuntimeError("库里只有 %d 个交易日，不足 %d" % (len(days), n_days))

    ph = ",".join(["%s"] * len(days))
    got = _q("select stock_code c, count(*) n from trade_stock_daily "
             "where trade_date in (" + ph + ") and volume > 0 and close_price > 0 "
             "group by stock_code", tuple(days))
    live = {x["c"]: int(x["n"]) for x in got}
    full = sorted([c for c, k in live.items() if k == len(days)])

    allst = _q("select count(distinct stock_code) n from trade_stock_daily")[0]["n"]
    ex = set(DEFAULT_EXCLUDE if exclude is None else exclude)
    in_ex = sorted([c for c in full if c in ex])
    codes = [c for c in full if c not in ex]

    res = {
        "codes": codes,
        "count": len(codes),
        "days": days,
        "universe": int(allst),
        "partial": len(live) - len(full),
        "never": int(allst) - len(live),
        "excluded": in_ex,
        "exclude_list": sorted(ex),
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "criteria": [
            "最近 %d 个交易日每一天都有成交（volume>0 且 close_price>0）" % n_days,
            "不在排除名单里（%d 只，所有区间都有价格断裂）" % len(ex),
        ],
    }
    if verbose:
        print("=" * 84)
        print("干净股票池 · %s" % res["as_of"])
        print("=" * 84)
        for c in res["criteria"]:
            print(" 判据: %s" % c)
        print(" 区间: %s → %s（%d 个交易日）" % (days[-1], days[0], len(days)))
        print()
        print(" 全表出现过 %6d 只" % res["universe"])
        print(" 最近区间全部有成交 %6d 只" % len(full))
        print(" → 干净池 %6d 只" % res["count"])
        print(" 部分有成交（排除） %6d 只" % res["partial"])
        print(" 完全无成交（排除） %6d 只" % res["never"])
        print(" 排除名单命中 %6d 只 %s" % (len(in_ex), ",".join(in_ex)))
        print()
        print(" 判据能失败: 池子为空 → 退出码 1")
    return res


def main():
    ap = argparse.ArgumentParser(description="干净股票池（只读数据库）")
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--check", default="")
    args = ap.parse_args()

    try:
        res = select(args.days, verbose=not args.json)
    except Exception as e:
        print(" 选池失败: %r" % (e,))
        return 1

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    if args.out:
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(res["codes"]) + "\n")
        print(" 已写出 %s（%d 行）" % (args.out, len(res["codes"])))
    if args.check:
        ok = args.check.strip() in set(res["codes"])
        print(" %s %s 在干净池里" % (args.check, "" if ok else " 不在"))
        return 0 if ok else 1
    return 0 if res["count"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
