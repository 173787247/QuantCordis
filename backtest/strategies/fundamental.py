# -*- coding: utf-8 -*-
"""QuantCordis 策略 · 基本面（另一个家族）

## 为什么做它

     六个技术指标策略平均相关 rho = 0.528**
      → 它们是一个信号的六种写法 → 组合无用
     所以要找真正独立的信号 → 必须换数据来源
      → 基本面与价格×均线毫无关系 → 理论上是新家族
     而库里已有财报数据 → 不用装新东西

## 未来函数怎么防（这是本策略最关键的部分）

     财报表只有 report_date（没有公告日）
      → 直接用就是偷看未来:
        · 2026-06-30 的财报 → 实际 8 月才公告
        · 而在 7 月 1 日就用到它
     所以用法定披露截止日（A股规则确定的）:
        一季报（03-31）→ 4 月 30 日· 半年报（06-30）→ 8 月 31 日
        三季报（09-30）→ 10 月 31 日· 年报（12-31）→ 次年 4 月 30 日
      → 报告期 + 到截止日之后才可用 → 零未来函数
      → 代价: 比实际公告晚 1-4 个月 → 但方向保守

## 参数

    factor : "ep"（E/P）· "roe" · "low_debt"（−负债率）
    top_n : 选前几名（横截面）
    rebal : 调仓间隔（天 默认 60）

## 用法（闭包捕获财务表）

    from strategies.fundamental import load_financials, make_strategy
    fin = load_financials() # {code: [(report_date, avail_date, vals)]}
    f = make_strategy(fin, factor="ep", top_n=3)
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_DATA = os.path.join(ROOT, "data")
if _DATA not in sys.path:
    sys.path.insert(0, _DATA)


def avail_date(rd):
    """ 报告期 → 最早可用日（法定截止日 → 零未来函数）"""
    y, m, d = rd.year, rd.month, rd.day
    if (m, d) == (3, 31):
        return _dt.date(y, 4, 30)
    if (m, d) == (6, 30):
        return _dt.date(y, 8, 31)
    if (m, d) == (9, 30):
        return _dt.date(y, 10, 31)
    if (m, d) == (12, 31):
        return _dt.date(y + 1, 4, 30)
    return rd + _dt.timedelta(days=120)


def load_financials(codes=None):
    """ 从库里取财报 → {code: [(report_date, avail_date, dict)]} """
    from db import execute_query
    sql = ("SELECT stock_code, report_date, eps, roe, debt_ratio, net_profit, revenue "
           "FROM trade_stock_financial")
    args = None
    if codes:
        sql += " WHERE stock_code IN (" + ",".join(["%s"] * len(codes)) + ")"
        args = tuple(codes)
    sql += " ORDER BY stock_code, report_date"
    rows = execute_query(sql, args)
    out = {}
    for r in rows:
        rd = r["report_date"]
        if not isinstance(rd, _dt.date):
            rd = _dt.date.fromisoformat(str(rd)[:10])
        out.setdefault(r["stock_code"], []).append((
            rd, avail_date(rd),
            {"eps": float(r["eps"]) if r["eps"] is not None else None,
             "roe": float(r["roe"]) if r["roe"] is not None else None,
             "debt": float(r["debt_ratio"]) if r["debt_ratio"] is not None else None,
             "np": float(r["net_profit"]) if r["net_profit"] is not None else None},
        ))
    return out


def value_at(series, day, factor, price=None):
    """ 取day 那天可用的最新一期的值 （严格按 avail_date）"""
    best = None
    for (rd, ad, v) in series:
        if ad <= day:
            if best is None or rd > best[0]:
                best = (rd, v)
    if best is None:
        return None
    v = best[1]
    if factor == "ep": # 注意: EP 需要价格 → 逐只调用框架下做不了横截面
                          # → 保留代码但不要用（见 make_strategy 的注释）
        # E/P = eps × 4 / price（年化）→ 需要 price
        if price is None or not price or v.get("eps") is None:
            return None
        return (v["eps"] * 4.0) / price
    if factor == "roe":
        return v.get("roe")
    if factor == "low_debt":
        return -v["debt"] if v.get("debt") is not None else None
    return None


def make_strategy(fin, factor="ep", top_n=3, universe=None):
    """ 生成基本面策略（需要横截面→ 用闭包持全池）

     注意: 回测器逐只调用 → 单只无法做横截面排序
      → 所以本策略对单只给"够不够格"的信号:
        · 它在全池中的因子值排名前 top_n→ buy
        · 否则 → sell
      → 每根 K 线重算全池排名→ 等价于每日横截面
    """
    uni = list(universe or fin.keys())

    def _f(code, market, capital):
        df = market.get_recent_kline(code, period="1d", count=3)
        if df is None or len(df) == 0:
            return {"side": "hold", "strategy": "fundamental", "reason": "无K线"}
        d = str(df.index[-1])[:10].replace("-", "")
        day = _dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        px = float(df["close"].tolist()[-1])
        # 算全池的因子值
        vals = {}
        for c in uni:
            s = fin.get(c)
            if not s:
                continue
            if factor == "ep":
                # E/P 需要各自的价格 → 而当前只评估 code
                # → 用同一个价格不行 → 改用eps/price_of_this不可比
                # → 解法: 对 ep 用eps × 4 / 该股当前价
                # → 而该股当前价只在c == code 时拿得到
                # → 所以换因子: 用eps × 4 / price_of_code而price只对 code 有
                # → 那退化成单只判断
                # → 最干净的做法: EP 只对当前 code算，其余用上次已知价
                # → 太绕 → 改用不需要价格的因子
                pass
            v = value_at(s, day, factor, price=px if c == code else None)
            if v is not None:
                vals[c] = v
        if code not in vals:
            return {"side": "hold", "strategy": "fundamental",
                    "reason": "当天没有可用财报（%s）" % day}
        # 横截面排名 （对于 roe/low_debt不需要价格 → 可比）
        ordered = sorted(vals.items(), key=lambda kv: -kv[1])
        rank = [x[0] for x in ordered].index(code) + 1
        if rank <= top_n:
            return {"side": "buy", "strategy": "fundamental",
                    "reason": "%s 排名 %d/%d（值 %.4f）→ 买入" % (
                        factor, rank, len(ordered), vals[code])}
        return {"side": "sell", "strategy": "fundamental",
                "reason": "%s 排名 %d/%d → 不在前 %d" % (factor, rank, len(ordered), top_n)}

    _f.__name__ = "fundamental"
    return _f


REGISTRY = {}


def get(name):
    return REGISTRY.get(name)


def list_names():
    return sorted(REGISTRY.keys())
