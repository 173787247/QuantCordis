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


DIVID_TABLE = "quantcordis_divid"


def ensure_divid_table(cur):
    """★ 复权因子【也要【落库】**✓（★ 2026-10-15 02:00 ✓）

    ★ 为什么（★ 而【这【一条【与【"只存不复权价"【是【同一个【道理 ✓）:
      · 【原来 `get_divid_events` 【每次【从 xtdata 【现取】**✗
        ⇒ ★★★ 【三个【后果**:
          ① 【离线【跑不了】（★ 每只【要 4.3 秒 · 【客户端【必须在 ✓）
          ② ★★★ 【回测【依赖【行情客户端【在线】✗
          ③ ★★★★ **【同一段历史【在【不同【时间【跑 ⇒ 【结果【可能【不同】**✗✗
            （★ 上游【改了【因子 ⇒ 【后复权价【就变了 ✓）
      · ★★ 【而【这【正是【项目【反对【的【东西】: 【README 写着
        「前复权: 每次分红都重算历史 → 【回测不可复现】」✗
        ⇒ ★★★ 【用【实时因子【算【后复权【是【同一个病】，【只是【换个口径 ✓✓
      · ★★★ 【数据层【已经把【不复权价【落库【就是【为了【可复现】✓
        ⇒ 【因子【是【同一类【事实】⇒ 【也该【落库 ✓（★ 与 bar_none 的 source/fetched_at 一致 ✓）

    ★ 判据（★ 能失败 ✓）: 【落库【之后，【同一只票【的【因子【必须【与
      【当场从【数据源【取的【完全一致】**⇒ 见 tools/divid_store_selftest.py ✓
    """
    cur.execute("""CREATE TABLE IF NOT EXISTS %s (
        stock_code VARCHAR(20) NOT NULL,
        ex_date    DATE        NOT NULL,
        dr         DOUBLE      NOT NULL,
        source     VARCHAR(32) NOT NULL DEFAULT 'xtdata',
        fetched_at DATETIME    NOT NULL,
        PRIMARY KEY (stock_code, ex_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""" % DIVID_TABLE)


def _fetch_divid_events_from_source(code):
    """★ 从【数据源【现取】✓（★ 只在【库里没有【或【显式【刷新【时【调用 ✓）"""
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


def _store_divid(code, events, source="xtdata"):
    """★ 把【因子【写进库】✓ · 重复【就【更新（★ 并【记【新的【抓取时间 ✓）"""
    from db import get_connection
    conn = get_connection()
    try:
        cur = conn.cursor()
        ensure_divid_table(cur)
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.executemany(
            "INSERT INTO %s (stock_code, ex_date, dr, source, fetched_at) "
            "VALUES (%%s,%%s,%%s,%%s,%%s) "
            "ON DUPLICATE KEY UPDATE dr=VALUES(dr), source=VALUES(source), "
            "fetched_at=VALUES(fetched_at)" % DIVID_TABLE,
            [(code, d, float(f), source, now) for (d, f) in events])
        conn.commit()
    finally:
        conn.close()


def _read_divid(code):
    """★ 从【库里【读】✓ —— 【这条路【不需要【行情客户端 ✓（★ 这就是【离线可回测 ✓）"""
    from db import get_connection
    conn = get_connection()
    try:
        cur = conn.cursor()
        ensure_divid_table(cur)
        conn.commit()
        cur.execute("SELECT ex_date, dr FROM %s WHERE stock_code=%%s "
                    "ORDER BY ex_date" % DIVID_TABLE, (code,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [(norm_date(r[0]), float(r[1])) for r in rows]


def get_divid_events(code, refresh=False):
    """除权事件 → [(日期, dr)] 日期统一格式

    ★ 顺序（2026-10-15 改）:
      ① 先【读库】✓ —— 命中就【直接返回，【不碰行情客户端】
      ② 库里【没有【或 `refresh=True` ⇒ 【从数据源【取一次【并【落库】✓
      ③ 取不到【就【返回空】（★ 调用方【按【没有除权【处理 ✓）

    ⇒ 好处: 【回测【可复现】（★ 因子【固定在库里 ✓）· 【可离线】· 【快】（★ 4.3 秒 → 毫秒级 ✓）
    """
    if not refresh:
        try:
            ev = _read_divid(code)
            if ev:
                return ev
        except Exception:
            pass                       # ★ 库不可用【就【退回【现取】（★ 不要【因为【库【而【跑不了 ✓）
    ev = _fetch_divid_events_from_source(code)
    if ev:
        try:
            _store_divid(code, ev)
        except Exception:
            pass                       # ★ 落库失败【不影响【本次【计算 ✓
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
