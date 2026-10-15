# -*- coding: utf-8 -*-
"""QuantCordis 最小回测器 —— 自带回测器

## 设计

    · market 对象自己写 → 不 import 外部回测器
      → 只实现策略需要的那一个接口: get_recent_kline(code, period, count)
      → 只返回当前索引之前的数据 → 避免未来函数

    · 策略函数复用 → 从 QUANTCORDIS_STRATEGY_ROOT 指向的目录 import
      → 为什么这是"复用"而不是"依赖":
        · 复用的是策略算法（纯函数 签名统一）
        · 不复用它的引擎 · 数据库 · 调度
      → 而且路径显式配置 → 没有它 QuantCordis 照样能跑数据层

    · 成交假设: 信号在 K_i 收盘出 → 用 K_{i+1} 开盘成交（参考实现也这样）
    · 成本: 佣金（双边）+ 印花税（卖出单边）
    · 没做: 滑点 · 冲击成本 → 已知缺口，写在这里

## 判据（能失败）

    同一 (策略, 票, 区间) 的净值曲线应当可复现
    → 不一致就说明有一边错了 → 那本身就是价值

## 用法

    python backtest/engine.py --code 600519.SH --strategy ma20_hold \
        --start 2018-01-01 --end 2026-06-30
"""
from __future__ import annotations
from datetime import datetime

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
if DATA not in sys.path:
    sys.path.insert(0, DATA)
# ★★★ 2026-10-15 02:05: 【自己的目录【也要加】—— 【否则【两种入口【行为【不同】**✓✓
#   ✗ 原来【只加了 DATA【没加 HERE】**✗
#     · ★ 【当脚本跑】（★ `python backtest/engine.py` ✓）⇒ 【Python 【自动【把【脚本目录
#       放在 sys.path[0]】✓ ⇒ 【`import strategies` 【能成 ✓
#     · ★★★ 【当库 import】（★ `from backtest.engine import run_backtest` ✓）⇒ 【没人加】✗
#       ⇒ **`import strategies` 【失败【 ⇒ 【被 `except Exception: pass` 【吞掉**
#         ⇒ ★★★★ 【本仓【自己【的【策略【全部【不可见】✗✗
#           （★ 实测: `limit_up` 报"策略库里没有"而【它【就在【本仓 ✓）
#           ⇒ 【能用的【全是【外部库【回退【来的 ✓
#   ⇒ ★ 【补这一行 ⇒ 【本仓【策略【在【两种入口下【都可见 ✓✓
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from adjust import back_adjust, front_adjust, get_divid_events, norm_date # noqa: E402
from db import execute_query # noqa: E402

TABLE = "quantcordis_bar_none"

# 数据缓存
# 为什么（实测）: 同一只票要跑多个策略 → 每次都查库 + 算复权
# 19 只 × 6 策略 = 114 次 → 查 114 次库 → 慢 5-6 倍
# → 加缓存后同一只票只加载一次
# 风险: 库里数据变了缓存不会失效
# → 所以只在单次进程内有效（不落盘）
# → 需要读最新数据时新起进程
_BARS_CACHE = {}
COMMISSION = 0.00025 # 佣金 万2.5（双边）
STAMP_DUTY = 0.0005 # 印花税 千0.5（只有股票有 → ETF 免）

ETF_COMMISSION = 0.00025 # ETF 佣金 万2.5（通常与股票同档）
ETF_STAMP = 0.0 # ETF 免印花税


def is_etf(code):
    """ 判断是否 ETF → 用不同费率

     为什么重要:
          ETF 免印花税 → 用股票费率会把成本算高一倍
          → 差之毫厘 → 可能把一个勉强可用的候选否掉
    """
    c = str(code).upper()
    p3 = c[:3]
    # 沪市 ETF: 51x/52x/56x/58x · 深市 ETF: 15x/16x
    return p3 in ("510", "511", "512", "513", "515", "516", "518", "588",
                  "159", "150", "160", "161", "162", "163", "164", "165",
                  "166", "167", "168", "169")


def load_bars(code, start=None, end=None, adjust="back"):
    """ 从库里取日K并复权 → [(date, open, high, low, close, volume)]

     加进程内缓存 → 同一只票多个策略只加载一次
    """
    key = (code, start, end, adjust)
    if key in _BARS_CACHE:
        return _BARS_CACHE[key]
    rows = execute_query(
        "SELECT trade_date, open_price, high_price, low_price, close_price, volume "
        "FROM %s WHERE stock_code=%%s ORDER BY trade_date" % TABLE, (code,))
    if not rows:
        raise RuntimeError("库里没有 %s（先跑 data/bar_none.py）" % code)
    dates = [norm_date(r["trade_date"]) for r in rows]
    o = [float(r["open_price"]) for r in rows]
    h = [float(r["high_price"]) for r in rows]
    l = [float(r["low_price"]) for r in rows]
    c = [float(r["close_price"]) for r in rows]
    v = [int(r["volume"] or 0) for r in rows]
    ev = get_divid_events(code)
    if adjust == "back":
        f = back_adjust(dates, c, ev)
        # 比例因子 → 用到开高低上 （同一因子）
        ratio = [f[i] / c[i] if c[i] else 1.0 for i in range(len(c))]
    elif adjust == "front":
        f = front_adjust(dates, c, ev)
        ratio = [f[i] / c[i] if c[i] else 1.0 for i in range(len(c))]
    else:
        ratio = [1.0] * len(c)
    o = [o[i] * ratio[i] for i in range(len(o))]
    h = [h[i] * ratio[i] for i in range(len(h))]
    l = [l[i] * ratio[i] for i in range(len(l))]
    c = [c[i] * ratio[i] for i in range(len(c))]
    if start:
        s = norm_date(start); e = norm_date(end) if end else "9999-99-99"
        idx = [i for i, d in enumerate(dates) if s <= d <= e]
        out = ([dates[i] for i in idx], [o[i] for i in idx], [h[i] for i in idx],
               [l[i] for i in idx], [c[i] for i in idx], [v[i] for i in idx])
    else:
        out = (dates, o, h, l, c, v)
    _BARS_CACHE[key] = out
    return out


class MiniMarket:
    """ 只实现策略需要的那一个接口 → 自己写，不 import 外部回测器

      性能修正（实测的瓶颈）
      → 2,126 天 × 6 策略 × 19 只 = 24 万次构造
      → 而 pandas 的 DataFrame 构造很贵 → 这才是真瓶颈
        （不是查库，那个已经缓存了）
      → 现在: 预建整张表一次 → 取数用 iloc 切片（视图，O(1)）
    """

    def __init__(self, code, bars):
        import pandas as pd
        self.code = code
        self._d, self._o, self._h, self._l, self._c, self._v = bars
        # 整张表只建一次
        self._df = pd.DataFrame({
            "open": self._o, "high": self._h, "low": self._l,
            "close": self._c, "volume": self._v,
        }, index=self._d)
        self.cur_idx = 0

    def get_recent_kline(self, code, period="1d", count=50):
        """ 只返回 cur_idx（含）之前的数据 → 避免未来函数

         切片是视图 → 不复制 → 快
        """
        end = self.cur_idx + 1
        start = max(0, end - count)
        return self._df.iloc[start:end]


def load_strategy(name):
    """ 取策略函数

     优先取 QuantCordis 自己的策略
      → 本目录 strategies/ 下的策略自带实现
      → 取不到再回退到 QUANTCORDIS_STRATEGY_ROOT 指向的策略库
    """
    # 0. 如果直接给了函数→ 用它
    # → 而那个错误信息误导—— 真实原因是参数类型
    # → 所以支持两种（闭包对情绪择时这种外部序列是必需的）
    if callable(name):
        return name
    # ① 先找自己的
    # ★★★ 2026-10-15 02:04: 【扫描 strategies/ 下所有模块，【不写死文件名】**✓✓
    #   ✗ 原来【写死 `import strategies.limit_up`]**✗
    #     ⇒ ★★ 【本仓【加一个策略【就得【回来改这一行】✗
    #       ⇒ 【而【这个函数【第一句【就写「优先取 QuantCordis 自己的策略」✓
    #         ⇒ ★★★ 【写死的 import 【让那句话【只对【一个文件【成立】**✗
    #   ⇒ ★ 【改成【遍历包内模块】（★ 加策略 = 加文件 ⇒ 【零改引擎 ✓✓）
    #     · 【约定【仍然是 `get(name)` ✓ · 返回 None 【就【继续找 ✓
    #     · ★★ 【某个模块【报错【就【跳过它】，【不【影响【其他策略 ✓
    try:
        import importlib
        import pkgutil
        import strategies as _pkg
        for _mi in pkgutil.iter_modules(_pkg.__path__):
            try:
                _mod = importlib.import_module("strategies." + _mi.name)
            except Exception:
                continue
            _get = getattr(_mod, "get", None)
            if not callable(_get):
                continue
            try:
                _f = _get(name)
            except Exception:
                continue
            if _f is not None:
                return _f
    except Exception:
        pass
    # ② 回退到外部策略库
    return _load_external(name)


def _load_external(name):
    """ 从量化的策略库 import 一个策略函数

     路径来自环境变量 QUANTCORDIS_STRATEGY_ROOT
      → 没配就报错并说明 → 但数据层不依赖它（只有回测需要）
    """
    root = (os.environ.get("QUANTCORDIS_STRATEGY_ROOT") or "").strip()
    if not root or not os.path.isdir(root):
        raise RuntimeError(
            "没有配置策略库目录。请设置环境变量 QUANTCORDIS_STRATEGY_ROOT "
            "指向含 lib/strategy_registry.py 的目录，例如 "
            "export QUANTCORDIS_STRATEGY_ROOT=/path/to/legacy-system")
    if root not in sys.path:
        sys.path.insert(0, root)
    from lib.strategy_registry import get_strategy
    meta = get_strategy(name)
    if meta is None:
        raise RuntimeError("策略库里没有 %r" % name)
    # StrategyMeta.evaluator 才是函数
    # TypeError: 'StrategyMeta' object is not callable
    # → 而当时被一个 try/except 吞掉了 → 0 笔交易
    # → 报告显示"策略收益 +0.00%" → 看起来像"策略不行"**
    return meta.evaluator


def run_backtest(code, strategy_name, start, end, adjust="back",
                 capital=100000.0, commission=COMMISSION, stamp=STAMP_DUTY,
                 debug=False, slippage=0.0, slippage_ticks=0):
    """ 滑点

     两种建模，都做（因为真实市场里两者都有）:
      · slippage: 固定比例（买 ×(1+s) · 卖 ×(1−s)）
      · slippage_ticks: 最小变动单位（A股 0.01 元 → 买 +0.01 · 卖 −0.01）
        → 它对低价股影响大、高价股影响小 → 那正是真实的
     买入持有基准也扣同口径滑点（否则比较不公平 各买卖一次）
    """
    """ 事件驱动的最简回测 返回 {navs, trades, metrics} """
    # 按标的类型自动选费率（ETF 免印花税）
    if is_etf(code):
        stamp = ETF_STAMP
        commission = commission if commission != COMMISSION else ETF_COMMISSION
    bars = load_bars(code, start, end, adjust=adjust)
    dates, o, h, l, c, v = bars
    n = len(dates)
    if n < 30:
        raise RuntimeError("数据不足（%d 根）" % n)
    strat = load_strategy(strategy_name)
    mkt = MiniMarket(code, bars)

    cash = capital
    shares = 0.0 # 浮点份额 → 不受"100 股"约束
    # ★★★ 2026-10-15 14:32: 【暴露 —— 每轮【都【该【报【的一个【数】**✓✓
    #   · 【为什么**: 【用"【相对【买入持有"【比【超额【时、【会【把"【会【空仓"【的【策略【算【高】✗
    #     （★ 因为【空仓【躲过【下跌【也【算【"【超额" ✓）⇒ 【实测 corr(超额, bh) = −0.87 ✓）
    #   · ★ 【所以要【知道【每个策略【到底【在【场【多久】✓ ⇒ 【暴露 = 【持仓【天数 ÷ 总天数 ✓
    #   · ★★ 【判据（★ 能失败 ✓）**: 【从不【交易 ⇒ **0**】· 【buy_and_hold ⇒ **1**】· 【其余【在 0~1 ✓
    #   · ★★★ 【这个【计数器【只【在【算净值【那一行【旁边【加一、【不【碰【任何【交易【分支 ✓✓
    days_in = 0
    sig_count = 0
    lot_warned = 0 # 因价格过高不足 1 手的次数 （不静默）
    navs, trades = [], []
    pending = None # 上一根出的信号 → 这根开盘执行

    for i in range(n):
        mkt.cur_idx = i
        px_open = o[i]
        # ① 先执行上一根留下的信号（用这根的开盘价）
        # 滑点后的成交价
        px_buy = px_open * (1 + slippage) + slippage_ticks * 0.01
        px_sell = px_open * (1 - slippage) - slippage_ticks * 0.01
        if pending and px_open > 0:
            if pending == "buy" and shares <= 0:
                # 浮点份额: 不按 100 股取整 → 测的是收益率序列
                shares = cash / (px_buy * (1 + commission))
                cash = 0.0
                trades.append({"date": dates[i], "side": "buy",
                               "price": round(px_buy, 4), "shares": round(shares, 4)})
                # 同时报出实盘约束: 该票按开盘价买 1 手要多少钱
                if px_open * 100 > capital:
                    lot_warned += 1
            elif pending == "sell" and shares > 0:
                cash = shares * px_sell * (1 - commission - stamp)
                trades.append({"date": dates[i], "side": "sell",
                               "price": round(px_sell, 4), "shares": round(shares, 4)})
                shares = 0.0
            pending = None
        # ② 这根收盘出信号 → 下一根开盘执行
        sig = strat(code, mkt, capital)
        if sig and sig.get("side") in ("buy", "sell"):
            sig_count += 1
            side = sig["side"]
            if debug and sig_count <= 6:
                print(" [信号] %s %s ← %s" % (
                    dates[i], side, str(sig.get("reason", ""))[:52]))
            if (side == "buy" and shares <= 0) or (side == "sell" and shares > 0):
                pending = side
        if shares > 0:
            days_in += 1
        navs.append(cash + shares * c[i])
    ret = (navs[-1] / capital - 1) * 100 if capital else 0
    peak = navs[0]; mdd = 0.0
    for x in navs:
        peak = max(peak, x)
        if peak > 0:
            mdd = max(mdd, (peak - x) / peak)
    # 买入持有也扣同口径滑点（买一次、卖一次 → 公平）
    _b0 = o[0] * (1 + slippage) + slippage_ticks * 0.01
    _b1 = c[-1] * (1 - slippage) - slippage_ticks * 0.01
    bh = (_b1 / _b0 - 1) * 100 if _b0 else 0
    return {
        "code": code, "strategy": strategy_name, "days": n,
        "start": dates[0], "end": dates[-1], "adjust": adjust,
        "total_return": ret, "max_drawdown": mdd * 100,
        "trades": len(trades), "signals": sig_count,
        "exposure": (days_in / n) if n else 0.0,        # ★ 持仓天数 ÷ 总天数 ✓
        "days_in_market": days_in,
        "lot_warned": lot_warned, "navs": navs, "trade_list": trades,
        "buy_hold": bh, "excess": ret - bh,
        "fees": {"commission": commission, "stamp_duty": stamp,
                 "slippage": slippage, "slippage_ticks": slippage_ticks},
        "capital": capital,
    }


def main():
    ap = argparse.ArgumentParser(description="QuantCordis 最小回测器")
    ap.add_argument("--code", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--adjust", default="back", choices=["back", "front", "none"])
    ap.add_argument("--debug", action="store_true", help=" 打印前几个信号 ")
    ap.add_argument("--slip", type=float, default=0.0, help=" 比例滑点（如 0.001 = 0.1%%）")
    ap.add_argument("--ticks", type=int, default=0, help=" 最小变动单位跳数（如 1 = 0.01 元）")
    args = ap.parse_args()
    r = run_backtest(args.code, args.strategy, args.start, args.end, args.adjust,
                     debug=args.debug, slippage=args.slip, slippage_ticks=args.ticks)
    print(" %s · %s · %s → %s（%d 天 · 复权=%s）" % (
        r["code"], r["strategy"], r["start"], r["end"], r["days"], r["adjust"]))
    print(" 策略收益 %+8.2f%% 买入持有 %+8.2f%% 超额 %+8.2f%%" % (
        r["total_return"], r["buy_hold"], r["excess"]))
    print(" 最大回撤 %.2f%% · 交易 %d 笔 · 信号 %d 个" % (
        r["max_drawdown"], r["trades"], r.get("signals", 0)))
    if args.slip or args.ticks:
        print(" 滑点: 比例 %.4f%% + %d 跳" % (args.slip * 100, args.ticks))
    if r.get("lot_warned"):
        print(" 提示: 有 %d 次按当时的开盘价，%d 元资金买不起 1 手"
              "→ 这是真实的实盘约束（回测用浮点份额，不受它影响）"
              % (r["lot_warned"], int(r.get("capital", 100000))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
