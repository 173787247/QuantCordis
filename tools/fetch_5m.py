#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QuantCordis 数据层 · 5 分钟线（bar_5m）

## 为什么存它

   有两个策略只能在分钟级判断（macd_5min / dual_ma_5min），而日线回测器测不了它们。
   实测（2026-10-15）:
     · xtdata 的 5 分钟数据完整、列齐（含 amount 与 suspendFlag）
     · 100 只取到 100/100，共 1,168,200 根，批量下载 17.5 秒、取数 0.9 秒
     · 外推全市场约 0.6 亿根、约 7.3 GB、约 15 分钟

## 判据（能失败，而且已经用它验过一次）

    同一天、同一只票，**48 根 5 分钟的 volume 求和必须等于日K 那天的 volume**。

    实测 000001.SZ 2026-10-14: 5 分钟求和 969,082 · 日K 969,082 · 比值 **1.0000**。
    这一条同时证明两件事: 单位相同，而且分钟数据是完整的（没漏根）。

## 与日K 表的约定保持一致

    · 只存**不复权**价 —— 复权用时算（与 quantcordis_bar_none 同一套理由）
    · 每条带 source 与 fetched_at ⇒ 可追溯到哪天抓的
    · 主键 (stock_code, bar_time) ⇒ 重跑不会写重

## 用法

    python tools/fetch_5m.py --limit 100        # 先试 100 只
    python tools/fetch_5m.py                    # 库里全部标的
    python tools/fetch_5m.py --verify           # 跑那条判据（同一天求和比对）
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

TABLE = "quantcordis_bar_5m"
COLS = ("stock_code, bar_time, open_price, high_price, low_price, close_price, "
        "volume, amount, pre_close, suspend_flag, source, fetched_at")
PH = ", ".join(["%s"] * 12)
BATCH = 100


def _conn():
    from db import get_connection
    return get_connection()


def ensure_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS %s (
        stock_code   VARCHAR(20)  NOT NULL,
        bar_time     DATETIME     NOT NULL,
        open_price   DOUBLE       NULL,
        high_price   DOUBLE       NULL,
        low_price    DOUBLE       NULL,
        close_price  DOUBLE       NULL,
        volume       BIGINT       NULL,
        amount       DOUBLE       NULL,
        pre_close    DOUBLE       NULL,
        suspend_flag TINYINT      NULL,
        source       VARCHAR(32)  NOT NULL DEFAULT 'xtdata',
        fetched_at   DATETIME     NOT NULL,
        PRIMARY KEY (stock_code, bar_time),
        KEY idx_time (bar_time)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""" % TABLE)


def codes(limit=0):
    import db
    rows = db.execute_query(
        "SELECT DISTINCT stock_code FROM quantcordis_bar_none ORDER BY stock_code")
    cs = [r["stock_code"] for r in rows]
    return cs[:limit] if limit else cs


def _fmt(t):
    """xtdata 的 5 分钟时间戳是 'YYYYMMDDHHMMSS' 字符串。"""
    s = str(t)
    if len(s) >= 14:
        return "%s-%s-%s %s:%s:%s" % (s[0:4], s[4:6], s[6:8], s[8:10], s[10:12], s[12:14])
    return s


def fetch_batch(xtdata, batch, start):
    """取一批 ⇒ {code: rows}。"""
    xtdata.download_history_data2(batch, period="5m", start_time=start, end_time="")
    d = xtdata.get_market_data_ex([], batch, period="5m", start_time=start,
                                  end_time="", count=-1)
    out = {}
    for c in batch:
        df = (d or {}).get(c)
        if df is None or len(df) == 0:
            continue
        # ★★★ 2026-10-15 15:54: 【价格【全空【的【行【不写库】**✓✓
        #   · ✗ 【第一版【照收】**✗ ⇒ 【全量【落库 7209 万行、【其中 **1195 万行（16.58%）【价格【全空**】✗✗
        #     （★ 集中在【数据源【最早【那几天：只有【极少数【票【有价、【其余【是【空壳行 ✓）
        #   · ★★ 【后果**: 【它们【永远【被【加载器【丢掉】（★ 已【在【engine 里【挡 ✓）⇒ 【只【占空间、
        #     【每次【加载【还要【过一遍】✗
        #     ⇒ ★ 后来【我【把【那 1195 万行【删了】（★ 判据: 加载结果【一字不变 ✓）
        #       ⇒ ★★★ 【而【不【堵【源头、【再跑【一次【采集【它们【就【回来】✗✓ ⇒ 【所以【在这里【拦 ✓
        #   · ★ 【判据（★ 能失败 ✓）**: 【**修【之后【再【采集、【新增【的【价格空行【必须【是 0**】✓
        rows = []
        _skip = 0
        for i in range(len(df)):
            r = df.iloc[i]
            _o, _h, _l, _cl = (_f(r.get("open")), _f(r.get("high")),
                               _f(r.get("low")), _f(r.get("close")))
            if _o is None and _h is None and _l is None and _cl is None:
                _skip += 1          # ★ 价格【全空 ⇒ 【不写 ✓（不静默、【最后报数 ✓）】
                continue
            rows.append((c, _fmt(df.index[i]),
                         _o, _h, _l, _cl, _i(r.get("volume")), _f(r.get("amount")),
                         _f(r.get("preClose")), _i(r.get("suspendFlag"))))
        if _skip:
            print("   %s: 跳过 %d 根价格全空的 bar（%.1f%%）"
                  % (c, _skip, 100.0 * _skip / max(1, len(df))), flush=True)
        out[c] = rows
    return out


def _f(v):
    """★ 2026-10-15 12:47: 【NaN 也要【变成 None】**✓✓

    ✗ 【第一版【只挡了 None】**✗ ⇒ 【全量抓取【成功 97 · 失败 **5088**】✗✗
      · 【报错**: `nan can not be used with MySQL`**✗
      · 【根因**: 【pandas 的缺失值【是 `float("nan")`】✓
        ⇒ `float(nan)` 【不报错】（★ nan 是合法 float ✓）⇒ **【写到 MySQL 【才炸** ✓
      · ★★ 【而【试写 10 只【没暴露】：【那 10 只【恰好【没有 NaN**✗
        ⇒ ★★★ 【教训**: 【小样本【能验【通路，【验不了【数据形态 ✓✓
    """
    try:
        if v is None:
            return None
        f = float(v)
        import math
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        if v is None:
            return None
        f = float(v)
        import math
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def verify(xtdata, sample):
    """判据: 同一天 5 分钟 volume 求和 == 日K 那天的 volume。"""
    import db
    ok = True
    for code in sample:
        # ★★★ 2026-10-15 12:12: 【必须【排除【今天】**✓✓
        #   ✗ 【第一版【取"【日K 表【最新那天"】**✗
        #     · 【而【今天（★ 盘中 ✓）【也有【一行】—— 【是【运行 daily 时【写进去的
        #       【**半天【的【部分K**】✗（★ 实测: 5 分钟只有 24 根 ⇒ 09:30–11:30 ✓）
        #     · ⇒ 【拿【今天【半天【去比【半天【当然【差】✗（★ 比值 0.88 / 0.97 / 0.98 ✓）
        #   · ★ 【所以【要【比【**两边【都是【完整交易日**】的那一天 ✓
        row = db.execute_query(
            "SELECT trade_date FROM trade_stock_daily WHERE stock_code=%s "
            "AND trade_date < CURDATE() ORDER BY trade_date DESC LIMIT 1", (code,))
        if not row:
            print("   %-12s 日K 表里没有 ⇒ 跳过" % code)
            continue
        day = str(row[0]["trade_date"])[:10]
        tag = day.replace("-", "")
        d = xtdata.get_market_data_ex([], [code], period="5m",
                                      start_time=tag + "000000",
                                      end_time=tag + "235959", count=-1)
        df = (d or {}).get(code)
        if df is None or len(df) == 0:
            print("   %-12s %s 取不到 5 分钟 ⇒ 跳过" % (code, day))
            continue
        v5 = float(df["volume"].sum())
        vd = float((db.execute_query(
            "SELECT volume FROM trade_stock_daily WHERE stock_code=%s AND trade_date=%s",
            (code, day))[0] or {}).get("volume") or 0)
        ratio = vd / v5 if v5 else 0
        same = abs(ratio - 1.0) < 1e-6
        ok = ok and same
        print("   %-12s %s · 5分钟 %d 根 求和=%.0f · 日K=%.0f · 比值 %.4f ⇒ %s"
              % (code, day, len(df), v5, vd, ratio, "一致" if same else "不一致"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20250101", help="起始（默认近一年）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--verify", action="store_true", help="只跑判据")
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    from xtquant import xtdata
    xtdata.connect()

    if args.verify:
        print("判据: 同一天 5 分钟 volume 求和 == 日K 那天的 volume")
        sample = codes(args.limit or 3)[:3]
        ok = verify(xtdata, sample)
        print("结论: %s" % ("通过" if ok else "失败"))
        return 0 if ok else 1

    cs = codes(args.limit)
    print("抓 5 分钟线: %d 只 · 起始 %s · 每批 %d" % (len(cs), args.start, args.batch))
    conn = _conn()
    cur = conn.cursor()
    ensure_table(cur)
    conn.commit()

    ok = fail = 0
    bars = 0
    t0 = time.time()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for i in range(0, len(cs), args.batch):
        batch = cs[i:i + args.batch]
        try:
            got = fetch_batch(xtdata, batch, args.start)
        except Exception as e:
            fail += len(batch)
            print("   批次 %d 失败: %s: %s" % (i, type(e).__name__, str(e)[:70]), flush=True)
            continue
        for c, rows in got.items():
            try:
                cur.executemany(
                    "INSERT INTO %s (%s) VALUES (%s) "
                    "ON DUPLICATE KEY UPDATE close_price=VALUES(close_price), "
                    "volume=VALUES(volume), amount=VALUES(amount), "
                    "fetched_at=VALUES(fetched_at)" % (TABLE, COLS, PH),
                    [r + ("xtdata", now) for r in rows])
                ok += 1
                bars += len(rows)
            except Exception as e:
                fail += 1
                print("   写 %s 失败: %s" % (c, str(e)[:70]), flush=True)
        conn.commit()
        done = min(i + args.batch, len(cs))
        el = time.time() - t0
        print("   进度 %d/%d · 成功 %d · 失败 %d · %d 根 · %.0f 秒"
              % (done, len(cs), ok, fail, bars, el), flush=True)
        _ = got

    print()
    print("完成: 成功 %d 只 · 失败 %d · 写入 %d 根 · %.0f 秒" % (ok, fail, bars, time.time() - t0))
    cur.execute("SELECT COUNT(DISTINCT stock_code), COUNT(*) FROM %s" % TABLE)
    r = cur.fetchone() or (0, 0)
    print("库中现有: %s 只 · %s 根" % (r[0], r[1]))
    conn.close()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
