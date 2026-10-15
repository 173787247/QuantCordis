#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把筛选结论固化成一个数据文件 —— 免得每次都要重算。

## 为什么有它

2026-10-15 一共判了 15 个策略（日K 13 个 + 5 分钟 2 个），而结论散在两个 jsonl 与几段对话里。
下一个会话（或用户）要回答「这个策略行不行」时，还得重新算一遍。

## 判据

    每个出现过的策略都必须有两个样本的记录，且每条都带分母（几只票）。

    · 少一个策略、或某个样本的分母是空 ⇒ 判据红。
    · 这个判据是能失败的：从两批结果合成，任何一边缺了都会露。

## 用法

    python tools/strategy_verdicts.py                    # 生成 outputs/strategy_verdicts.json
    python tools/strategy_verdicts.py --show             # 顺便打印一张表
"""
from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "outputs", "strategy_verdicts.json")

# 两个样本 + 五分钟那批（单只票的数也记下来，但分母会写明）
SOURCES = [
    ("old_1056", "screen_full.jsonl", "旧样本（干净池每五取一）"),
    ("new_1036", "screen_repl88.jsonl", "新样本（与旧样本零交集）"),
]


def load(rel):
    rows = []
    fp = os.path.join(ROOT, "outputs", rel)
    if not os.path.isfile(fp):
        return rows
    for line in io.open(fp, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
            if o.get("excess") is not None:
                rows.append(o)
        except Exception:
            pass
    return rows


def verdict(ex):
    """三条判据: 均值>0 且 中位>0 且 为正>50%。"""
    e = sorted(ex)
    m = sum(e) / len(e)
    md = statistics.median(e)
    pos = sum(1 for x in e if x > 0)
    return {"mean": round(m, 4), "median": round(md, 4),
            "positive": pos, "n": len(e),
            "pass_mean": m > 0, "pass_median": md > 0,
            "pass_positive": pos > len(e) / 2,
            "pass_all": bool(m > 0 and md > 0 and pos > len(e) / 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    out = {"note": "判据: 均值超额>0 且 中位超额>0 且 为正只数>50%；分母写在每个 n 上",
           "samples": {}}
    allstrat = set()
    for key, rel, label in SOURCES:
        rows = load(rel)
        by = {}
        for r in rows:
            by.setdefault(r["strategy"], []).append(float(r["excess"]))
        out["samples"][key] = {"label": label, "source": rel,
                               "n_stocks": len(rows), "strategies": {}}
        for s in sorted(by):
            out["samples"][key]["strategies"][s] = verdict(by[s])
            allstrat.add(s)

    # ★ 判据: 每个策略【都【必须【在【两【个【样本里【出现 ✓
    missing = []
    for s in sorted(allstrat):
        for key, _rel, _lab in SOURCES:
            d = out["samples"][key]["strategies"]
            if s not in d or not d[s].get("n"):
                missing.append("%s@%s" % (s, key))
    out["check"] = {"strategies": sorted(allstrat), "missing": missing,
                    "ok": not missing}
    os.makedirs(os.path.join(ROOT, "outputs"), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=1))

    print("策略数: %d" % len(allstrat))
    print("判据（每个策略两个样本都要有、且分母非空）: %s"
          % ("通过" if not missing else "失败 -> %s" % missing[:5]))
    print("已写: %s" % OUT)
    if args.show:
        print()
        print("%-18s %10s %10s %6s %s" % ("策略", "旧均值", "新均值", "两样本", "判定"))
        for s in sorted(allstrat):
            o = out["samples"]["old_1056"]["strategies"].get(s, {})
            n = out["samples"]["new_1036"]["strategies"].get(s, {})
            both = o.get("pass_all") and n.get("pass_all")
            print("%-18s %+9.2f%% %+9.2f%% %6s %s"
                  % (s, o.get("mean", 0), n.get("mean", 0),
                     "%d/%d" % (o.get("n", 0), n.get("n", 0)),
                     "两个都过" if both else ("一个过" if (o.get("pass_all") or n.get("pass_all")) else "都不过")))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
