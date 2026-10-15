#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把大盘指数落库 —— 用于「相对大盘」的第二个视角。

## 为什么要它

    现在回测的超额 = 策略收益 − **同期买入持有该票**。那是「选股/择时有没有加分」，
    但它回答不了另一个同样重要的问题: **相对大盘呢**。
    两个视角不冲突，指数只是把第二个视角的数据先备好。

## 为什么单独一张表

    指数和个股混进 `quantcordis_bar_none` 会让按标的全表扫描的东西（策略筛选）
    把它们当成股票回测。所以单独一张，结构照抄日K 表。

## 判据（能失败）

    取之前先 `download_history_data` —— 实测不下载时 000905/000001/399006 三只都取不到，
    下载后四只全有（672 根、到当天）。所以「取不到」要先怀疑没下载过，别当成没有。

## 用法

    python tools/fetch_index.py            # 抓默认四个
    python tools/fetch_index.py --list     # 只看现在有哪些
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

TABLE = "quantcordis_index_daily"
COLS = ("index_code, trade_date, open_price, high_price, low_price, close_price, "
        "volume, amount, source, fetched_at")
PH = ", ".join(["%s"] * 10)

# ★ 四个常用基准（实测都能取到 ✓）
DEFAULT = ["000300.SH",   # 沪深300
           "000905.SH",   # 中证500
           "000001.SH",   # 上证指数
           "399006.SZ"]   # 创业板指


def _conn():
    from db import get_connection
    return get_connection()


def ensure_table(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS %s (
        index_code  VARCHAR(20) NOT NULL,
        trade_date  DATE        NOT NULL,
        open_price  DOUBLE      NULL,
        high_price  DOUBLE      NULL,
        low_price   DOUBLE      NULL,
        close_price DOUBLE      NULL,
        volume      BIGINT      NULL,
        amount      DOUBLE      NULL,
        source      VARCHAR(32) NOT NULL DEFAULT 'xtdata',
        fetched_at  DATETIME    NOT NULL,
        PRIMARY KEY (index_code, trade_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""" % TABLE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default=",".join(DEFAULT))
    ap.add_argument("--start", default="20050101")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        import db
        for r in db.execute_query(
                "SELECT index_code, COUNT(*) AS n, MIN(trade_date) AS d0, MAX(trade_date) AS d1 "
                "FROM %s GROUP BY index_code ORDER BY index_code" % TABLE):
            print("   %-12s %5s 根 · %s → %s"
                  % (r["index_code"], r["n"], str(r["d0"])[:10], str(r["d1"])[:10]))
        return 0

    from xtquant import xtdata
    xtdata.connect()
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    conn = _conn()
    cur = conn.cursor()
    ensure_table(cur)
    conn.commit()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    ok = 0
    for c in codes:
        t0 = time.time()
        # ★ 判据就在这一行: 先下载，再取 ✓
        xtdata.download_history_data(c, period="1d", start_time=args.start, end_time="")
        d = xtdata.get_market_data_ex([], [c], period="1d",
                                      start_time=args.start, end_time="", count=-1)
        df = (d or {}).get(c)
        if df is None or len(df) == 0:
            print("   %-12s ⇒ **下载后仍取不到**" % c)
            continue
        det = xtdata.get_instrument_detail(c) or {}
        rows = []
        for i in range(len(df)):
            r = df.iloc[i]
            # ★★★ 2026-10-15 13:03: 【日期转换【写清楚】**✓
            #   ✗ 我【第一版【写成了一串 `... and ...`】✗ —— 【又臭【又【看不出【意图 ✓
            #   · ★ xtdata 的日线索引【是 'YYYYMMDD' 字符串】（★ 也可能【是数字 ✓）
            #     ⇒ 【统一【转成 'YYYY-MM-DD' ✓ · 【转不了【就【跳过这一行】（★ 不【塞脏数据 ✓）
            _d = _to_date(df.index[i])
            if _d is None:
                continue
            rows.append((c, _d,
                         _f(r.get("open")), _f(r.get("high")), _f(r.get("low")),
                         _f(r.get("close")), _i(r.get("volume")), _f(r.get("amount"))))
        cur.executemany(
            "INSERT INTO %s (%s) VALUES (%s) "
            "ON DUPLICATE KEY UPDATE close_price=VALUES(close_price), "
            "volume=VALUES(volume), amount=VALUES(amount), fetched_at=VALUES(fetched_at)"
            % (TABLE, COLS, PH),
            [r + ("xtdata", now) for r in rows])
        conn.commit()
        ok += 1
        print("   %-12s %-12s %5d 根 · %s → %s · %.1f 秒"
              % (c, det.get("InstrumentName") or "", len(rows),
                 str(df.index[0])[:8], str(df.index[-1])[:8], time.time() - t0))
    print()
    print("完成: %d/%d 只" % (ok, len(codes)))
    cur.execute("SELECT COUNT(DISTINCT index_code), COUNT(*) FROM %s" % TABLE)
    r = cur.fetchone() or (0, 0)
    print("库中现有: %s 个指数 · %s 根" % (r[0], r[1]))
    conn.close()
    return 0


def _to_date(v):
    """把 xtdata 的日期（'YYYYMMDD' 或数字）转成 'YYYY-MM-DD'；转不了返回 None。"""
    s = str(v)
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 8:
        return None
    return "%s-%s-%s" % (digits[:4], digits[4:6], digits[6:8])


def _f(v):
    try:
        if v is None:
            return None
        import math
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        if v is None:
            return None
        import math
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else int(f)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
