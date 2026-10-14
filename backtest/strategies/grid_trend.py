# -*- coding: utf-8 -*-
"""QuantCordis 策略 · 网格 + 趋势过滤（构造，不是抄来的）

## 为什么构造它（依据是一次筛选的实测，不是感觉）

在一千零五十二只上跑 grid_classic，结果是这样的：

    均值超额 +3.94% · 中位超额 +33.51% · 703/1052 为正 · 均交易 27.3 次

中位与为正比例都很好，而均值被拖到只剩三点九四。这说明**信号是真的，是左尾把它拉下来的**。

grid_classic 的判据是 60 日高低切八格，底部两格买、顶部两格卖、跌破下界止损。
在持续下跌的票上，60 日区间会一路下移，「底部两格」就一路是买点 —— 它在一路接飞刀，
而「跌破下界才止损」那时已经晚了一个区间。左尾就是这么来的。

## 构造

只改一件事：**买入要带趋势条件**。

    买入: 原来「底部两格」再 && 收盘价 > 自己的 ma_period 日均线
    卖出: 不变（顶部两格 / 涨破上界 / 跌破下界）
    被趋势挡住的买点 ⇒ hold，并在 reason 里写清是被挡住的

为什么是均线：它是「这只票整体在往上还是往下」的最省事判据，参数只有一个，
而且不引入新数据源 —— 只用日 K。

为什么不顺便调网格格数：那会多一个参数。参数量本身是过拟合风险，先只加一个。

## 参数（只有两个）

    ma_period : 趋势均线长度，默认 200
    格数 8 与「底部/顶部两格」沿用 grid_classic，不改

## 签名（与回测器一致，可被直接调用）

    f(code, market, capital) -> {"side": "buy"/"sell"/"hold", "strategy": ..., "reason": ...}
"""
from __future__ import annotations

import pandas as pd

NAME = "grid_trend"

# ★ 参数（只有两个；改这里就是改策略，不要藏别的常数）
MA_PERIOD = 200
GRID_CELLS = 8
BUY_CELLS = 2          # 底部几格算低吸
SELL_CELLS = 2         # 顶部几格算高抛
EDGE_BUFFER = 0.02     # 上下各留 2% 缓冲（与 grid_classic 一致）


def _hold(reason: str) -> dict:
    return {"side": "hold", "strategy": NAME, "reason": reason}


def _signal(side: str, reason: str) -> dict:
    return {"side": side, "strategy": NAME, "reason": reason}


def grid_trend(code: str, market, capital: float, ma_period: int = MA_PERIOD) -> dict:
    need = max(ma_period, 60) + 10
    try:
        df = market.get_recent_kline(code, period="1d", count=need)
    except Exception as e:
        return _hold("取不到日K: %s" % str(e)[:50])
    if df is None or len(df) < 60:
        return _hold("日 K 不足 60 根")

    close = df["close"].astype(float)
    cur = float(close.iloc[-1])

    # ── 趋势过滤（本策略唯一的改动）────────────────────────────────
    if len(close) < ma_period:
        return _hold("日 K 不足 %d 根，趋势判不了" % ma_period)
    ma = float(close.iloc[-ma_period:].mean())
    uptrend = cur > ma

    # ── 网格（与 grid_classic 同一套）──────────────────────────────
    high_60 = float(df["high"].iloc[-60:].max())
    low_60 = float(df["low"].iloc[-60:].min())
    if high_60 <= low_60:
        return _hold("网格区间无效")

    margin = (high_60 - low_60) * EDGE_BUFFER
    upper = high_60 + margin
    lower = low_60 - margin
    size = (upper - lower) / GRID_CELLS
    idx = int((cur - lower) / size) if size > 0 else GRID_CELLS // 2
    idx = max(0, min(GRID_CELLS - 1, idx))

    reason = ("区间[%.2f,%.2f] 当前=%.2f 第 %d/%d 格 · 均线%d=%.2f · %s"
              % (lower, upper, cur, idx + 1, GRID_CELLS, ma_period, ma,
                 "在均线上方" if uptrend else "在均线下方"))

    # ── 出界处理（不变）────────────────────────────────────────────
    if cur < lower:
        return _signal("sell", "跌破下界 %.2f -> 止损 " % lower + reason)
    if cur > upper:
        return _signal("sell", "涨破上界 %.2f -> 止盈 " % upper + reason)

    # ── 买要带趋势；卖不带（该走就走）────────────────────────────
    if idx < BUY_CELLS:
        if not uptrend:
            return _hold("底部低吸被趋势挡住（在均线下方） " + reason)
        return _signal("buy", "底部低吸（且均线上方） " + reason)
    if idx >= GRID_CELLS - SELL_CELLS:
        return _signal("sell", "顶部高抛 " + reason)
    return _hold(reason)


def get(name):
    """回测器按名字取策略（与 lib/strategy_registry.py 的约定一致）。"""
    if name == NAME:
        return grid_trend
    return None
