# -*- coding: utf-8 -*-
"""QuantCordis 自己的策略 · A股独有现象（涨停/连板）

## 为什么从这里起步

     公开技术指标策略已实测无效:
      6 个策略 × 19 只主板 × 含真实费率与滑点 → 平均超额一个都没有为正
      → 而外部资料也说「公开因子已被 4000+ 机构挖干净」
     → 换空间 —— 找 A股独有的现象
      · 涨跌停制度 → 全球主要市场里只有 A股 等少数有
      · 连板 / 炸板 / 一字板 → 这些概念在美股不存在
     为什么先做涨停而不是龙虎榜/资金流 :
      · 涨停能从日K 直接算 → 不需要新数据源
      · 龙虎榜 / 资金流需要额外数据 → 下一轮

## 信号口径（只用日K）

     涨停判定: 主板 ±10% → 用 ≥ 9.8%（留出四舍五入与 ST 的 5% 不管）
      → 为什么不用 10% 整 : 涨停价按前收四舍五入到分
        → 有时 9.98% 有时 10.02% → 9.8% 是稳的界
     首板: 今日涨停 且 昨日未涨停（第一个板）
     排除一字板: 开盘价 == 收盘价 且 涨停
      → 为什么排除 : 一字板买不进（真实约束 不是策略选择）
     卖出: 持有 N 天 或跌破买入价 X%**
      → 参数只有两个 → 不容易过拟合

## 签名（与旧策略库一致 → 可直接被回测器调用）

    f(code, market, capital) -> {"side": "buy"/"sell"/"hold", "strategy": ..., "reason": ...}
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 默认参数（只有两个 → 少 → 不容易过拟合）
HOLD_DAYS = 3 # 持有天数
STOP_LOSS = 0.05 # 跌破买入价 5% 就走
LIMIT_THRESHOLD = 0.098 # 涨停判定阈值（9.8%）


def _is_limit_up(close, pre_close, th=LIMIT_THRESHOLD):
    """ 是否涨停 （只用日K）"""
    if not pre_close or pre_close <= 0 or close <= 0:
        return False
    return (close / pre_close - 1) >= th


def _is_one_word_board(row):
    """ 是否一字板 → 买不进 → 排除"""
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    return o > 0 and o == h == l == c


def limit_up_first_board(code, market, capital, hold_days=HOLD_DAYS,
                         stop_loss=STOP_LOSS):
    """ 首板策略（纯函数 与策略库同签名）

     状态从哪来 : 回测器每根都调用一次 → 而它无状态
      → 所以"买入后持有 N 天"这个状态回测器不知道
      → 简单可靠的做法: 只用 K 线判断"该不该持有"**
        · 买: 首板
        · 卖: 首板后的第 N 天 或跌破止损
        → 而"首板后的第 N 天"可以从 K 线序列算出来（往回数）
    """
    df = market.get_recent_kline(code, period="1d", count=max(30, hold_days + 5))
    if df is None or len(df) < 5:
        return {"side": "hold", "strategy": "limit_up_first_board",
                "reason": "K 线不足"}
    # preClose 从哪来 : 库里存了 但 market 只给 OHLCV
    # → 用前一根的收盘（对日K 这是标准做法）
    c = [float(x) for x in df["close"].tolist()]
    o = [float(x) for x in df["open"].tolist()]
    h = [float(x) for x in df["high"].tolist()]
    l = [float(x) for x in df["low"].tolist()]
    n = len(c)

    # 卖出判断: 往回数 hold_days 根前是否首板
    for k in range(1, min(hold_days + 1, n - 1)):
        i = n - 1 - k # 候选的"首板日"
        if i < 1:
            break
        is_lu = _is_limit_up(c[i], c[i-1])
        prev_lu = _is_limit_up(c[i-1], c[i-2]) if i >= 2 else False
        if is_lu and not prev_lu:
            # 那根是首板 → 从它之后已经持有了 k 天
            if k >= hold_days:
                return {"side": "sell", "strategy": "limit_up_first_board",
                        "reason": "首板后已持有 %d 天 → 到期卖出" % k}
            # 止损: 现价相对首板次日的开盘价
            entry = o[i+1] if i + 1 < n else c[i]
            if entry > 0 and (c[n-1] / entry - 1) <= -stop_loss:
                return {"side": "sell", "strategy": "limit_up_first_board",
                        "reason": "首板后跌破买入价 %.1f%% → 止损" % (
                            (1 - c[n-1] / entry) * 100)}
            return {"side": "hold", "strategy": "limit_up_first_board",
                    "reason": "首板后持有中（第 %d 天）" % k}

    # 买入判断: 最新一根是否首板（且非一字板）
    i = n - 1
    if i < 1:
        return {"side": "hold", "strategy": "limit_up_first_board", "reason": "K 线不足"}
    is_lu = _is_limit_up(c[i], c[i-1])
    prev_lu = _is_limit_up(c[i-1], c[i-2]) if i >= 2 else False
    if is_lu and not prev_lu:
        if _is_one_word_board({"open": o[i], "high": h[i], "low": l[i], "close": c[i]}):
            return {"side": "hold", "strategy": "limit_up_first_board",
                    "reason": "首板是一字板 → 买不进 → 不追"}
        return {"side": "buy", "strategy": "limit_up_first_board",
                "reason": "首板（%.2f→%.2f，+%.1f%%）" % (
                    c[i-1], c[i], (c[i]/c[i-1] - 1) * 100)}
    return {"side": "hold", "strategy": "limit_up_first_board", "reason": "无首板"}


# 注册（供回测器按名字取）
REGISTRY = {
    "limit_up_first_board": limit_up_first_board,
}


def get(name):
    return REGISTRY.get(name)


def list_names():
    return sorted(REGISTRY.keys())


if __name__ == "__main__":
    print("QuantCordis 自有策略: %s" % ", ".join(list_names()))
