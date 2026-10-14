# -*- coding: utf-8 -*-
"""QuantCordis 策略 · 市场情绪择时（A股独有）

## 思路

     实测: 涨停占比（按板块判定）与次日收益正相关
      · 可交易 ETF 上: 沪深300ETF −0.0131% < 中证500ETF +0.1106% < 中证1000ETF +0.2136%
      · 市值越小信号越强 → 机制是中小盘的情绪溢出
      · 8/9 年为正 · 中位数高于均值（不靠离群值）

     所以策略是择时 不是选股:
      · 情绪高 → 持有 ETF**
      · 情绪低 → 空仓
      → 而它正好是"买入持有"的改进（避开低情绪期）

## 为什么用 ETF 而不是个股

     信号在小市值上最强 → 需要中小盘敞口
     ETF 提供该敞口，且不依赖单一标的
     → 所以要参与中小盘 → 用 ETF

## 参数（只有两个 → 不易过拟合）

    threshold : 情绪门槛（用训练期的分位点定 → 不看测试期）
    hold_min : 最小持有天数（减少来回交易 → 省成本）

## 用法（闭包捕获情绪序列）

    from market.sentiment import daily_sentiment
    from strategies.sentiment_timing import make_strategy
    sent = {d: v for (d, v, _s, _n, _t, _a) in daily_sentiment()}
    f = make_strategy(sent, threshold=0.0227)
    # f(code, market, capital) → {"side": ...}
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def make_strategy(sentiment, threshold=0.0227, hold_min=1, use_seal=False):
    """ 生成情绪择时策略（闭包捕获情绪序列）

     状态怎么处理 : 回测器每根都调用而它无状态
      → 所以"持有到什么时候"要从 K 线自身推断
      → 但情绪择时不需要 —— 它的规则是状态型:
        · 情绪 > 门槛 → 想持有
        · 情绪 ≤ 门槛 → 想空仓
      → 所以无状态 → 不需要 hold_min（保留参数以备实验）
    """
    def _f(code, market, capital):
        df = market.get_recent_kline(code, period="1d", count=3)
        if df is None or len(df) == 0:
            return {"side": "hold", "strategy": "sentiment_timing", "reason": "无K线"}
        # 当前这根 K 线的日期 → 查当天收盘后的情绪
        d = str(df.index[-1])[:10]
        d = d.replace("-", "")
        d = "%s-%s-%s" % (d[:4], d[4:6], d[6:8]) if len(d) >= 8 else d
        v = sentiment.get(d)
        if v is None:
            return {"side": "hold", "strategy": "sentiment_timing",
                    "reason": "当天没有情绪数据（%s）" % d}
        if v > threshold:
            return {"side": "buy", "strategy": "sentiment_timing",
                    "reason": "情绪 %.4f > 门槛 %.4f → 持有" % (v, threshold)}
        return {"side": "sell", "strategy": "sentiment_timing",
                "reason": "情绪 %.4f <= 门槛 %.4f → 空仓" % (v, threshold)}
    _f.__name__ = "sentiment_timing"
    return _f


REGISTRY = {}


def get(name):
    return REGISTRY.get(name)


def list_names():
    return sorted(REGISTRY.keys())
