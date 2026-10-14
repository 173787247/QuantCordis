# -*- coding: utf-8 -*-
"""QuantCordis 数据层 · 不复权日K（bar_none）

## 设计（依据 QuantCordis/docs/DATA-LAYER-DESIGN.md）

     只存不复权价 —— 因为它是事实，不随任何基准变化
     复权用时算 —— 前复权 / 后复权从同一份数据算出 → 一套数据两种视图
     每条带 source 与 fetched_at → 可追溯到"哪天抓的"

## 为什么不用库的价格

    库存的是前复权 → 每次分红重算全部历史
    → 同一段回测在不同时间跑 → 输入不同 → 结果不同
    实测:
      · 茅台 2016-01-04 的 front 口径 = −87.8082（125 天 ≤ 0）
      · 而同一时期 none 口径 全部 > 0
      → 所以"只存 none"这个决定是实测出来的 不是推理的

## 两个来自数据源、比我们自己判更准的字段

    · suspendFlag → 停牌标志
        实测: 茅台在 2001-2026 有 74 天停牌
        （我原来打算用"close=0 且 volume=0"自己判 → 会漏掉）
    · preClose → 前收盘
        → 算涨跌幅不用自己找前一天 而且除权日它也正确

## 用法
    python bar_none.py --code 600519.SH # 拉一只并落库
    python bar_none.py --code 600519.SH --audit # 拉完做审计
    python bar_none.py --code 600519.SH --verify-twice # 两跑一致性（可复现判据）
## 退出码
    0 = 正常 · 1 = 审计不通过或两跑不一致（判据能失败）

## 数据归属
只写 quantcordis_* 表 不碰既有表
"""
from __future__ import annotations
import argparse, hashlib, io, os, sys, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 数据库连接自己管 自包含
from db import get_connection # noqa: E402

TABLE = "quantcordis_bar_none"
START, END = "20010101", "20261014"

DDL = """
CREATE TABLE IF NOT EXISTS {t} (
  stock_code VARCHAR(20) NOT NULL COMMENT '代码',
  trade_date DATE NOT NULL COMMENT '交易日',
  open_price DECIMAL(20,4) COMMENT '开盘(不复权)',
  high_price DECIMAL(20,4) COMMENT '最高',
  low_price DECIMAL(20,4) COMMENT '最低',
  close_price DECIMAL(20,4) COMMENT '收盘',
  volume BIGINT COMMENT '成交量(手)',
  amount DECIMAL(20,2) COMMENT '成交额(元)',
  suspend_flag TINYINT DEFAULT 0 COMMENT '停牌标志(数据源给)',
  pre_close DECIMAL(20,4) COMMENT '前收盘(除权日亦正确)',
  source VARCHAR(20) DEFAULT 'xtdata' COMMENT '来源',
  fetched_at DATETIME COMMENT '抓取时间(可追溯)',
  PRIMARY KEY (stock_code, trade_date),
  KEY idx_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='QuantCordis 不复权日K'
"""

COLS = ("stock_code, trade_date, open_price, high_price, low_price, close_price, "
        "volume, amount, suspend_flag, pre_close, source, fetched_at")
PH = ",".join(["%s"] * 12)


def _conn():
    """ 连不上会报错并说明怎么配（见 data/db.py）"""
    return get_connection()


def ensure_table(cur):
    cur.execute(DDL.format(t=TABLE))
    for col, ddl in (("suspend_flag", "TINYINT DEFAULT 0"),
                     ("pre_close", "DECIMAL(20,4)")):
        try:
            cur.execute("ALTER TABLE %s ADD COLUMN %s %s" % (TABLE, col, ddl))
        except Exception:
            pass


def fetch(code):
    """从 xtdata 拉不复权日K 返回可插入的行 """
    from xtquant import xtdata
    d = xtdata.get_market_data_ex([], [code], period="1d",
                                  start_time=START, end_time=END,
                                  dividend_type="none")
    df = (d or {}).get(code)
    if df is None or len(df) == 0:
        raise RuntimeError("xtdata 没有 %s 的数据" % code)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for i in range(len(df)):
        r = df.iloc[i]
        pc = r.get("preClose")
        rows.append((code, str(df.index[i])[:10],
                     float(r.get("open")), float(r.get("high")),
                     float(r.get("low")), float(r.get("close")),
                     int(r.get("volume") or 0), float(r.get("amount") or 0),
                     int(r.get("suspendFlag") or 0),
                     (float(pc) if pc is not None else None),
                     "xtdata", now))
    return rows


def write(cur, code, rows):
    cur.execute("DELETE FROM %s WHERE stock_code=%%s" % TABLE, (code,))
    cur.executemany("INSERT INTO %s (%s) VALUES (%s)" % (TABLE, COLS, PH), rows)


def fingerprint(cur, code):
    """ 内容指纹 —— 用于"两跑一致"这个可复现判据 """
    cur.execute("SELECT trade_date, close_price, volume, suspend_flag, pre_close "
                "FROM %s WHERE stock_code=%%s ORDER BY trade_date" % TABLE, (code,))
    h = hashlib.sha256()
    n = 0
    for r in cur.fetchall():
        h.update(("%s|%s|%s|%s|%s\n" % (r[0], r[1], r[2], r[3], r[4])).encode())
        n += 1
    return h.hexdigest(), n


def audit(cur, code):
    """ 审计 —— 判据能失败 返回 (通过?, 明细)"""
    bad = []
    cur.execute("SELECT COUNT(*) FROM %s WHERE stock_code=%%s AND "
                "(close_price<=0 OR open_price<=0 OR low_price<=0 OR high_price<=0)"
                % TABLE, (code,))
    n = cur.fetchone()[0]
    if n:
        bad.append("非正价格 %d 行" % n)
    cur.execute("SELECT COUNT(*) FROM %s WHERE stock_code=%%s" % TABLE, (code,))
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM %s WHERE stock_code=%%s AND suspend_flag=1"
                % TABLE, (code,))
    susp = cur.fetchone()[0]
    return (len(bad) == 0), {"总数": total, "停牌": susp, "问题": bad}


def main():
    ap = argparse.ArgumentParser(description="QuantCordis 不复权日K")
    ap.add_argument("--code", required=True)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--verify-twice", action="store_true",
                    help=" 拉两次并比对指纹（可复现判据）")
    args = ap.parse_args()

    conn = _conn(); cur = conn.cursor()
    ensure_table(cur); conn.commit()

    t0 = time.time()
    rows = fetch(args.code)
    write(cur, args.code, rows); conn.commit()
    print(" %s → 拉取并写入 %d 行（%.1f 秒）" % (args.code, len(rows), time.time()-t0))

    rc = 0
    if args.audit:
        ok, info = audit(cur, args.code)
        print(" 审计: 总数 %d · 停牌 %d · 问题 %s → %s"
              % (info["总数"], info["停牌"], info["问题"] or "无", "通过" if ok else "不通过"))
        if not ok:
            rc = 1

    if args.verify_twice:
        fp1, n1 = fingerprint(cur, args.code)
        write(cur, args.code, fetch(args.code)); conn.commit()
        fp2, n2 = fingerprint(cur, args.code)
        same = (fp1 == fp2 and n1 == n2)
        print(" 两跑指纹: %s… / %s… （%d / %d 行）→ %s"
              % (fp1[:16], fp2[:16], n1, n2, " 一致 → 可复现" if same else " 不一致"))
        if not same:
            rc = 1

    cur.close(); conn.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
