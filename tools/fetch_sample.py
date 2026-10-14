#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把不复权日K铺到一个【按判据抽出来】的样本上。

为什么要它
    `data/bar_none.py` 一次只收一只。而策略筛选需要横截面 —— 样本太小时结论会随样本翻转：
    同一个策略、同一区间、同一费率，样本从十九只换到二十五只，均值超额就从正四点六五变成
    负十九点三五。所以样本要么足够大，要么别下结论。

抽样判据（写在这里，不按结果挑）
    1. 取自干净池：最近 20 个交易日每一天都有成交，且不在排除名单里
    2. 按代码升序，每 STEP 只取 1 只
    3. 结果写入 quantcordis_bar_none；已存在的代码默认跳过（--force 才重拉）

用法
    python tools/fetch_sample.py --dry-run          # 只看样本，不抓数
    python tools/fetch_sample.py --step 5           # 按判据抓
    python tools/fetch_sample.py --step 5 --limit 20
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))


def clean_pool():
    """干净池（判据在 data/pool.py 里）。返回升序代码列表。"""
    import pool
    res = pool.select(n_days=20, verbose=False)
    codes = res.get("codes") or []
    return sorted(codes)


def sample(step):
    """按判据抽样：升序，每 step 只取 1 只。"""
    codes = clean_pool()
    return codes, codes[::max(1, int(step))]


def already(cur, code):
    # ★ 2026-10-15 01:09: 【这个游标【返回【元组，【不是【字典】**✓
    #   ✗ 我【第一版【照 `db.execute_query` 的【字典【写法【写了 `.get("n")`】**✗
    #     ⇒ ★★ 【实测**: `AttributeError: 'tuple' object has no attribute 'get'`
    #       · （★ `bar_none._conn()` 没给 DictCursor ⇒ 【裸 pymysql ⇒ 元组 ✓）
    #   ⇒ ★ 【按下标取】✓
    cur.execute("SELECT COUNT(*) FROM quantcordis_bar_none WHERE stock_code = %s", (code,))
    row = cur.fetchone()
    return bool(row and int(row[0] or 0) > 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=5, help="升序每 N 只取 1（默认 5）")
    ap.add_argument("--limit", type=int, default=0, help="最多抓几只（0 = 不限）")
    ap.add_argument("--dry-run", action="store_true", help="只列样本，不抓数")
    ap.add_argument("--force", action="store_true", help="已有数据也重拉")
    args = ap.parse_args()

    import bar_none as bn

    full, picked = sample(args.step)
    if args.limit:
        picked = picked[:args.limit]
    print("干净池 %d 只 · 抽样判据 升序每 %d 只取 1 ⇒ 样本 %d 只" % (len(full), args.step, len(picked)))
    print("前 5 只: %s" % ", ".join(picked[:5]))
    if args.dry_run:
        return 0

    conn = bn._conn()
    cur = conn.cursor()
    bn.ensure_table(cur)
    conn.commit()

    ok = skipped = failed = 0
    bars = 0
    t0 = time.time()
    for i, code in enumerate(picked, 1):
        if not args.force and already(cur, code):
            skipped += 1
            continue
        try:
            rows = bn.fetch(code)
            if not rows:
                failed += 1
                print("  [%d/%d] %s 拉不到数据" % (i, len(picked), code), flush=True)
                continue
            bn.write(cur, code, rows)
            conn.commit()
            ok += 1
            bars += len(rows)
        except Exception as e:
            failed += 1
            conn.rollback()
            print("  [%d/%d] %s 失败: %s: %s"
                  % (i, len(picked), code, type(e).__name__, str(e)[:80]), flush=True)
        if i % 25 == 0:
            el = time.time() - t0
            print("  进度 %d/%d · 成功 %d · 跳过 %d · 失败 %d · %d 行 · %.0f 秒"
                  % (i, len(picked), ok, skipped, failed, bars, el), flush=True)

    el = time.time() - t0
    print()
    print("完成: 成功 %d · 跳过 %d · 失败 %d · 写入 %d 行 · %.0f 秒"
          % (ok, skipped, failed, bars, el))
    cur.execute("SELECT COUNT(DISTINCT stock_code), COUNT(*) FROM quantcordis_bar_none")
    r = cur.fetchone() or (0, 0)
    print("库中现有: %s 只 · %s 行" % (r[0], r[1]))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
