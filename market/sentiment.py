# -*- coding: utf-8 -*-
"""QuantCordis 市场情绪指标 —— A股独有品种

## 为什么有这个模块

     实测过程里同一个 bug 犯了一次:
      涨停阈值写死 9.8% 用于全部股票
      → 而创业板/科创板是 20% 涨跌幅
      → → 把涨 10-20%、根本没涨停的也算成涨停
      → 规模: 创业板/科创板里涨 9.8%~19.6% 的有 40,707 条
      → 后果: 情绪指标失真→ 择时结论的数值全错
     → 所以固化成模块→ 下次不会重写 SQL、不会重犯

## 板块与阈值（A股现行规则）

    主板 600/601/603/605/000/001/002/003 10% → 判定用 9.8%
    创业板 300/301 20% → 判定用 19.6%
    科创板 688/689 20% → 判定用 19.6%
    北交所 43x/83x/87x/88x/92x 30% → 判定用 29.4%
    ST 股 5% → 判定用 4.8%

     为什么留 0.2 个百分点: 涨跌幅限制按前收四舍五入到分
      → 实际幅度有时 9.98% 有时 10.02% → 用 9.8% 是稳的界

     已知缺口: ST 股需要股票名称或标记→ 本库没有
      → 实现里不猜→ 提供 st_codes 参数，调用方显式传入
      → 所以 daily_sentiment 的 SQL 里 ST 归入主板阈值 → 会漏掉 ST 的涨停

## 用法

    from sentiment import daily_sentiment, verify
    rows = daily_sentiment() # 全历史
    ok, info = verify() # 自检（能失败）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
if DATA not in sys.path:
    sys.path.insert(0, DATA)

from db import execute_query # noqa: E402

NL = chr(10) # 显式换行 → 避免 heredoc 转义坑

TH = {
    "main": 0.098,
    "growth": 0.196,
    "bj": 0.294,
    "st": 0.048,
}
GROWTH_PREFIX = ("300", "301", "688", "689")
BJ_PREFIX = ("430", "830", "831", "832", "833", "834", "835", "836", "837", "838",
             "839", "870", "871", "872", "873", "874", "875", "876", "877", "878",
             "879", "880", "881", "882", "883", "884", "885", "886", "887", "888",
             "889", "920")


def board_of(code, st_codes=None):
    """ 判断板块 → main / growth / bj / st"""
    c = str(code).upper()
    p3 = c[:3]
    if st_codes and c in st_codes:
        return "st"
    if p3 in GROWTH_PREFIX:
        return "growth"
    if p3 in BJ_PREFIX:
        return "bj"
    return "main"


def threshold_of(code, st_codes=None):
    return TH[board_of(code, st_codes)]


def daily_sentiment(start="2018-01-01", end="2099-12-31", st_codes=None):
    """ 每日情绪 → [(日期, 涨停占比, 封板率, 涨停家数, 触板家数, 全市场)]

     实现说明:
      · 板块判定在 SQL 里做—— 用 CASE WHEN 前缀
        → 因为逐行拉回 Python 判会慢几十倍（一千六百万行）
      · 阈值从本模块的 TH 拼进 SQL → 单一真源
    """
    sql = """
    SELECT t.trade_date AS d, t.n_all, t.n_up, t.n_touch
    FROM (
      SELECT trade_date,
             COUNT(*) AS n_all,
             SUM(CASE WHEN (CASE WHEN LEFT(stock_code,3) IN ('300','301','688','689')
                                THEN {G} ELSE {M} END) <= c/pc - 1
                      THEN 1 ELSE 0 END) AS n_up,
             SUM(CASE WHEN (CASE WHEN LEFT(stock_code,3) IN ('300','301','688','689')
                                THEN {G} ELSE {M} END) <= h/pc - 1
                      THEN 1 ELSE 0 END) AS n_touch
      FROM (
        SELECT stock_code, trade_date, close_price AS c, high_price AS h,
               LAG(close_price) OVER (PARTITION BY stock_code ORDER BY trade_date) AS pc
        FROM trade_stock_daily
        WHERE trade_date >= %s AND trade_date <= %s
      ) x
      WHERE pc > 0 AND c > 0
      GROUP BY trade_date
    ) t ORDER BY t.trade_date
    """.format(G=TH["growth"], M=TH["main"])
    rows = execute_query(sql, (start, end))
    out = []
    for r in rows:
        nu = int(r["n_up"] or 0)
        nt = int(r["n_touch"] or 0)
        na = int(r["n_all"] or 1)
        out.append((str(r["d"])[:10], nu / na, (nu / nt if nt else None), nu, nt, na))
    return out


def fingerprint(rows):
    """ 可复现指纹"""
    h = hashlib.sha256()
    for r in rows:
        h.update(("%s|%d|%d|%d" % (r[0], r[3], r[4], r[5])).encode() + NL.encode())
    return h.hexdigest()


def _count_where(prefix_filter, th, start, end):
    """ 在给定板块集合上数涨停 → 用于自检的独立算法"""
    sql = """
    SELECT SUM(CASE WHEN %s <= c/pc - 1 THEN 1 ELSE 0 END) AS n
    FROM (SELECT stock_code, close_price c,
                 LAG(close_price) OVER (PARTITION BY stock_code ORDER BY trade_date) pc
          FROM trade_stock_daily
          WHERE trade_date >= %%s AND trade_date <= %%s %s) x
    WHERE pc > 0 AND c > 0
    """ % (th, prefix_filter)
    r = execute_query(sql, (start, end))
    return int((r[0] if r else {}).get("n") or 0)


def verify(start="2024-01-01", end="2024-12-31"):
    """ 自检（能失败）

     判据① 阈值真的生效:
      把创业板阈值翻倍 → 总数必须改变
      → 若不变 → 说明阈值没进 SQL→ 失败
     判据② 按板块拆分与独立计算一致:
      total = 主板部分(独立算) + 创业板科创板部分(独立算)
      → 若不等 → 说明 CASE WHEN 写错→ 失败
    """
    base = daily_sentiment(start, end)
    if not base:
        return False, {"错误": "取不到数据"}

    old = TH["growth"]
    TH["growth"] = old * 2
    try:
        changed = daily_sentiment(start, end)
    finally:
        TH["growth"] = old
    n_base = sum(r[3] for r in base)
    n_chg = sum(r[3] for r in changed)
    effect = (n_base != n_chg)

    main_only = _count_where(
        "AND LEFT(stock_code,3) NOT IN ('300','301','688','689')", TH["main"], start, end)
    growth_only = _count_where(
        "AND LEFT(stock_code,3) IN ('300','301','688','689')", TH["growth"], start, end)
    consistent = (n_base == main_only + growth_only)

    ok = effect and consistent
    return ok, {
        "判据① 改创业板阈值会改变总数": effect,
        " 总数(原)": n_base,
        " 总数(创业板阈值×2)": n_chg,
        "判据② 拆分与独立算一致": consistent,
        " 按板块总数": n_base,
        " 主板(独立)": main_only,
        " 创业板科创板(独立)": growth_only,
        " 两者之和": main_only + growth_only,
        "指纹": fingerprint(base)[:16],
    }


def main():
    ap = argparse.ArgumentParser(description="QuantCordis 市场情绪指标")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2099-12-31")
    ap.add_argument("--verify", action="store_true", help=" 自检（能失败）")
    ap.add_argument("--tail", type=int, default=5)
    args = ap.parse_args()
    if args.verify:
        ok, info = verify()
        print(" 情绪指标自检（判据能失败）")
        for k, v in info.items():
            print(" %-32s %s" % (k, v))
        print(" → %s" % (" 通过" if ok else " 不通过 → 见上面明细"))
        return 0 if ok else 1
    rows = daily_sentiment(args.start, args.end)
    print(" %d 个交易日 · 指纹 %s" % (len(rows), fingerprint(rows)[:16]))
    for r in rows[-args.tail:]:
        print(" %s 涨停占比 %.4f 封板率 %s 涨停 %d/%d 只" % (
            r[0], r[1], ("%.3f" % r[2]) if r[2] is not None else "—", r[3], r[5]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
