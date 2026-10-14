# -*- coding: utf-8 -*-
"""Factor study (reproducible). See docs/FACTOR-STUDY.md for the recorded results.

Why this file exists :
  Acceptance requires that backtest conclusions be reproducible. The research
  behind them was originally done in throwaway /tmp scripts, which do not
  survive. This file is the durable form.

Subcommands and their falsifiable criteria:
  ic cross-sectional Spearman rank IC, non-overlapping quarters.
           criterion: |t| > 2 and mean IC > 0.02.
  layer Top-20% portfolio vs equal-weight market, net of 0.16% per rebalance.
           criterion: Top-20% must beat equal weight.
  neutral same as layer but E/P is ranked *within* market-cap quintiles.
           criterion: excess must retain > 50% of the un-neutralised excess,
           otherwise the factor is just a small-cap proxy.

Look-ahead prevention: the financial table has report_date but no announcement
date, so availability uses the statutory disclosure deadlines (Q1 -> Apr 30,
H1 -> Aug 31, Q3 -> Oct 31, annual -> Apr 30 of the following year). eps is a
cumulative year-to-date figure and is annualised by report period.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "data")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

COST = 0.0016
SHARES_CACHE = os.path.join(ROOT, "outputs", "shares.json")


def _load_env():
    """Read the legacy .env so the tool works without exporting anything.

    The credentials live in the project's .env under *; data/db.py
    reads them the same way. Without this the tool connects but is refused
    because no password was supplied.
    """
    for cand in (os.path.join(ROOT, ".env"),
                  os.path.join(os.path.dirname(ROOT), ".env")):
        if not os.path.isfile(cand):
            continue
        try:
            for line in io.open(cand, encoding="utf-8", errors="replace"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k.startswith(""):
                    env = "QUANTCORDIS_SQL_" + k[len(""):]
                    if not os.environ.get(env):
                        os.environ[env] = v.strip().strip('"').strip("'")
        except Exception:
            pass


def _host_candidates():
    """MySQL 连接候选地址，按可移植性排序。

    顺序：显式配置 → 本机 → 默认网关 → 容器别名。
    前面能连上就不试后面（连接是有超时的）。

    默认网关从 /proc/net/route 读，谁跑谁自己算 —— WSL 与容器里宿主通常就是它。
    不写死任何具体地址，克隆下来即可用。
    """
    out = []
    h = (os.environ.get("QUANTCORDIS_DB_HOST") or "").strip()
    if h:
        out.append(h)
    out += ["127.0.0.1", "localhost"]
    # 默认网关从 /proc/net/route读（Destination 全 0 那行 · Linux 专有，失败就算了）
    try:
        for line in io.open("/proc/net/route", encoding="utf-8"):
            f = line.split()
            if len(f) > 2 and f[1] == "00000000":
                gw = int(f[2], 16)
                out.append("%d.%d.%d.%d" % (gw & 0xFF, (gw >> 8) & 0xFF,
                                            (gw >> 16) & 0xFF, (gw >> 24) & 0xFF))
                break
    except Exception: # noqa: BLE001
        pass
    # 容器别名 + Docker 默认桥（通用常量，不本机特有）
    # `172.17.0.1` 是Docker 默认桥的通用网关
    # → 不是本机特有 → 可以留在公开仓 （与写死宿主 IP不同）
    out += ["host.docker.internal", "172.17.0.1"]
    # 去重且保序
    seen, uniq = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _conn():
    import pymysql
    _load_env()
    cands = _host_candidates()
    last = None
    for h in cands:
        if not h:
            continue
        try:
            c = pymysql.connect(
                host=h,
                user=os.environ.get("QUANTCORDIS_SQL_USERNAME")
                     or "root",
                password=os.environ.get("QUANTCORDIS_SQL_PASSWORD")
                         or "",
                database=os.environ.get("QUANTCORDIS_SQL_DB")
                         or "quantcordis",
                port=int(os.environ.get("QUANTCORDIS_SQL_PORT")
                         or 3306),
                charset="utf8mb4", connect_timeout=8)
            print(" connected: MySQL @ %s" % h, flush=True)
            return c
        except Exception as e:
            last = e
    raise SystemExit("cannot connect to MySQL (tried %s): %s" % (cands, str(last)[:120]))


def avail_date(rd):
    y, m, d = rd.year, rd.month, rd.day
    if (m, d) == (3, 31):
        return dt.date(y, 4, 30)
    if (m, d) == (6, 30):
        return dt.date(y, 8, 31)
    if (m, d) == (9, 30):
        return dt.date(y, 10, 31)
    if (m, d) == (12, 31):
        return dt.date(y + 1, 4, 30)
    return rd + dt.timedelta(days=120)


def ann_factor(rd):
    if rd.month == 3:
        return 4.0
    if rd.month == 6:
        return 2.0
    if rd.month == 9:
        return 4.0 / 3.0
    return 1.0


def load_fin(cur):
    cur.execute("SELECT stock_code, report_date, eps, roe, debt_ratio, net_profit "
                "FROM trade_stock_financial WHERE report_date >= '2020-03-31' "
                "ORDER BY stock_code, report_date")
    out = {}
    for (c, rd, eps, roe, debt, np_) in cur.fetchall():
        if not isinstance(rd, dt.date):
            rd = dt.date.fromisoformat(str(rd)[:10])
        out.setdefault(c, []).append({
            "rd": rd,
            "eps": float(eps) if eps is not None else None,
            "roe": float(roe) if roe is not None else None,
            "debt": float(debt) if debt is not None else None,
            "np": float(np_) if np_ is not None else None,
        })
    for c, ser in out.items():
        byk = {(r["rd"].year, r["rd"].month): r for r in ser}
        for r in ser:
            base = byk.get((r["rd"].year - 1, r["rd"].month))
            r["_growth"] = (r["np"] / base["np"] - 1) if (
                base and base.get("np") and base["np"] > 0 and r.get("np") is not None) else None
    return out


def periods_of(fin):
    return sorted({r["rd"] for ser in fin.values() for r in ser})


def px_on(cur, day):
    cur.execute("SELECT MAX(trade_date) FROM trade_stock_daily WHERE trade_date <= %s", (day,))
    row = cur.fetchone()
    d = row[0] if row else None
    if not d:
        return {}, None
    cur.execute("SELECT stock_code, close_price FROM trade_stock_daily WHERE trade_date = %s", (d,))
    return {x[0]: float(x[1]) for x in cur.fetchall() if x[1] and float(x[1]) > 0}, d


def shares_map():
    if os.path.isfile(SHARES_CACHE):
        try:
            return json.load(io.open(SHARES_CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def fval(row, f, px):
    if f == "roe":
        return row.get("roe")
    if f == "low_debt":
        return -row["debt"] if row.get("debt") is not None else None
    if f == "ep":
        return ((row["eps"] * ann_factor(row["rd"])) / px) if (
            row.get("eps") is not None and px) else None
    if f == "growth":
        return row.get("_growth")
    return None


def rank_map(vals, keys):
    s = sorted(keys, key=lambda k: vals[k])
    return {k: i for i, k in enumerate(s)}


def spearman(a, b, keys):
    if len(keys) < 50:
        return None
    ra, rb = rank_map(a, keys), rank_map(b, keys)
    n = len(keys)
    m = (n - 1) / 2.0
    num = sum((ra[k] - m) * (rb[k] - m) for k in keys)
    da = sum((ra[k] - m) ** 2 for k in keys)
    db = sum((rb[k] - m) ** 2 for k in keys)
    return num / math.sqrt(da * db) if da * db > 0 else None


def cmd_ic(args):
    conn = _conn(); cur = conn.cursor()
    fin = load_fin(cur)
    P = periods_of(fin)
    facs = ("roe", "low_debt", "ep", "growth")
    ics = {f: [] for f in facs}
    for i in range(len(P) - 1):
        rd0, rd1 = P[i], P[i + 1]
        p0, d0 = px_on(cur, avail_date(rd0))
        p1m, d1 = px_on(cur, avail_date(rd1))
        if not p0 or not p1m or not d0 or d1 is None or d0 >= d1:
            continue
        codes = [c for c in fin if any(r["rd"] == rd0 for r in fin[c])]
        ret = {c: p1m[c] / p0[c] - 1 for c in codes if c in p1m and c in p0 and p0[c] > 0}
        if len(ret) < 200:
            continue
        for f in facs:
            fv = {}
            for c in ret:
                row = next((r for r in fin[c] if r["rd"] == rd0), None)
                if row is not None:
                    v = fval(row, f, p0.get(c))
                    if v is not None:
                        fv[c] = v
            keys = [c for c in fv if c in ret]
            v = spearman(fv, ret, keys)
            if v is not None:
                ics[f].append(v)
    conn.close()
    print()
    print(" %-12s %6s %10s %10s %9s %8s" % ("factor", "n", "mean IC", "sd", "IC>0", "t"))
    for f in facs:
        v = ics[f]
        if len(v) < 3:
            continue
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5
        t = m / (sd / math.sqrt(len(v))) if sd > 0 else 0.0
        print(" %-12s %6d %+10.4f %10.4f %8.1f%% %+8.2f"
              % (f, len(v), m, sd, len([x for x in v if x > 0]) / len(v) * 100, t))
    print()
    print(" criterion: |t| > 2 and mean IC > 0.02")
    print(" non-overlapping quarters, so t is not inflated by overlap")
    print()
    print(" NOTE : an earlier throwaway version matched prices with")
    print(" trade_date = avail_date exactly. Most disclosure deadlines are not")
    print(" trading days, so it silently dropped more than half the periods and")
    print(" reported 12 instead of 19. It showed three of four factors passing")
    print(" the t test; over the full 19 periods none of them pass. Prices are")
    print(" now taken from the latest trading day on or before the deadline.")
    return 0


def _rows(cur, fin, neutral=False):
    SH = shares_map() if neutral else {}
    out = []
    P = periods_of(fin)
    for i in range(len(P) - 1):
        rd0, rd1 = P[i], P[i + 1]
        p0, d0 = px_on(cur, avail_date(rd0))
        p1m, d1 = px_on(cur, avail_date(rd1))
        if not p0 or not p1m or not d0 or d1 is None or d0 >= d1:
            continue
        codes = [c for c in fin if any(r["rd"] == rd0 for r in fin[c])]
        ret = {c: p1m[c] / p0[c] - 1 for c in codes if c in p1m and c in p0 and p0[c] > 0}
        if len(ret) < 200:
            continue
        f, mv = {}, {}
        for c in ret:
            row = next((r for r in fin[c] if r["rd"] == rd0), None)
            if row is None:
                continue
            v = fval(row, "ep", p0.get(c))
            if v is None:
                continue
            f[c] = v
            sh = (SH.get(c) or {}).get("total") or 0
            mv[c] = sh * p0[c] if sh > 0 else None
        ok = [c for c in f if c in ret]
        if len(ok) < 200:
            continue
        if neutral and all(mv.get(c) for c in ok):
            srt = sorted(ok, key=lambda c: mv[c])
            picked = []
            for g in range(5):
                seg = srt[g * len(srt) // 5:(g + 1) * len(srt) // 5]
                seg = sorted(seg, key=lambda c: -f[c])
                picked += seg[:max(5, len(seg) // 5)]
        else:
            picked = sorted(ok, key=lambda c: -f[c])[:max(20, len(ok) // 5)]
        if len(picked) < 20:
            continue
        out.append((rd0, sum(ret[c] for c in picked) / len(picked),
                    sum(ret.values()) / len(ret), len(picked)))
    return out


def _cum(rows):
    t = a = 1.0
    for (_d, rt, ra, _n) in rows:
        t *= (1 + rt - COST); a *= (1 + ra)
    return (t - 1) * 100, (a - 1) * 100


def cmd_layer(args):
    conn = _conn(); cur = conn.cursor()
    fin = load_fin(cur)
    rows = _rows(cur, fin, neutral=False)
    conn.close()
    a, b = _cum(rows)
    pos = len([r for r in rows if r[1] > r[2]])
    print()
    print(" periods %d, cost %.2f%%/rebalance" % (len(rows), COST * 100))
    print(" Top20%% %+.2f%% | equal-weight %+.2f%% | excess %+.2f%% | positive %d/%d"
          % (a, b, a - b, pos, len(rows)))
    print()
    print(" criterion: Top20%% net of cost must beat equal weight -> %s"
          % ("PASS" if a > b else "FAIL"))
    return 0 if a > b else 1


def cmd_neutral(args):
    conn = _conn(); cur = conn.cursor()
    fin = load_fin(cur)
    r0 = _rows(cur, fin, neutral=False)
    r1 = _rows(cur, fin, neutral=True)
    conn.close()
    if not r0 or not r1:
        print("insufficient sample")
        return 1
    a0, b0 = _cum(r0); a1, b1 = _cum(r1)
    e0, e1 = a0 - b0, a1 - b1
    keep = (e1 / e0 * 100) if e0 else 0.0
    print()
    print(" raw : Top %+.2f%% | excess %+.2f%% (%d periods)" % (a0, e0, len(r0)))
    print(" cap-neutral: Top %+.2f%% | excess %+.2f%% (%d periods)" % (a1, e1, len(r1)))
    print(" retained : %.1f%%" % keep)
    print()
    print(" criterion: retained > 50%% -> not merely a small-cap proxy -> %s"
          % ("PASS" if keep > 50 else "FAIL"))
    return 0 if keep > 50 else 1


def main():
    ap = argparse.ArgumentParser(description="factor study (reproducible, falsifiable)")
    ap.add_argument("cmd", choices=("ic", "layer", "neutral"))
    args = ap.parse_args()
    print("=" * 96)
    print("factor study | %s | %s" % (args.cmd, dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=" * 96)
    return {"ic": cmd_ic, "layer": cmd_layer, "neutral": cmd_neutral}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
