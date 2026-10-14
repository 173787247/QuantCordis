# -*- coding: utf-8 -*-
"""QuantCordis 的数据库连接 —— 自己读配置 · 自己连

 设计要点: 别人 clone 后只需配自己的库
  → 自包含 · 不假设目录结构

## 配置来源（按优先级）

① 环境变量 QUANTCORDIS_SQL_HOST / USERNAME / PASSWORD / DB / PORT
② 一个 .env 文件（按顺序找: 本仓库根 / 上级目录）
③ 内置默认（localhost · root · quantcordis · 3306 只对本地开发有意义）

## 用法

    from db import get_connection, execute_query
    rows = execute_query("select 1 as x")

## 注意

     本模块只负责连接 → 只读既有表、只写 quantcordis_* 新表
     密码不入库 → 走环境变量或 .env（后者已在 .gitignore 里）
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKSPACE = os.path.dirname(ROOT)

ENV_CANDIDATES = [
    os.path.join(ROOT, ".env"),
    os.path.join(WORKSPACE, ".env"),
]

# 环境变量键名
KEYS = {
    "host": "QUANTCORDIS_SQL_HOST",
    "user": "QUANTCORDIS_SQL_USERNAME",
    "password": "QUANTCORDIS_SQL_PASSWORD",
    "database": "QUANTCORDIS_SQL_DB",
    "port": "QUANTCORDIS_SQL_PORT",
}
DEFAULTS = {"host": "localhost", "user": "root", "password": "",
            "database": "quantcordis", "port": 3306}


def _load_env_files():
    """把 .env 读进一个 dict（不污染 os.environ 便于排查）"""
    out = {}
    for path in ENV_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass
    return out


def sql_config(verbose=False):
    """组装连接参数 —— 四层回退 """
    env = _load_env_files()
    cfg = {}
    src = {}
    for field, key in KEYS.items():
        v = (os.environ.get(key) or "").strip()
        if v:
            cfg[field] = v; src[field] = key; continue
        v = (env.get(key) or "").strip()
        if v:
            cfg[field] = v; src[field] = key + "(.env)"; continue
        cfg[field] = DEFAULTS[field]; src[field] = "默认"
    cfg["port"] = int(cfg["port"])
    cfg["charset"] = "utf8mb4"
    if verbose:
        for k in ("host", "port", "database", "user"):
            print(" %-10s = %-16s (%s)" % (k, cfg[k], src[k]))
        print(" %-10s = %s" % ("password", "<已设置>" if cfg["password"] else "<空>"))
    return cfg


def get_connection():
    """ 连不上就报错并说明怎么配（能失败）"""
    try:
        import pymysql
    except ImportError:
        raise RuntimeError("需要 pymysql: pip install pymysql")
    cfg = sql_config()
    try:
        return pymysql.connect(**cfg)
    except Exception as e:
        raise RuntimeError(
            "连不上数据库（%s@%s:%s/%s）: %s\n"
            "请用环境变量配置: QUANTCORDIS_SQL_HOST / USERNAME / PASSWORD / DB / PORT\n"
            "或在本仓库根放一个 .env（已在 .gitignore 里）"
            % (cfg["user"], cfg["host"], cfg["port"], cfg["database"], e))


def execute_query(sql, params=None):
    """查询 → 返回字典行列表

     沿用旧实现验证过的一条经验: params 为 None 时不要传空元组
      传 () 会触发 PyMySQL 的 `query % args` 格式化 → 任何含字面 % 的语句都会炸
    """
    import pymysql
    conn = get_connection()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


if __name__ == "__main__":
    print("QuantCordis 数据库配置:")
    sql_config(verbose=True)
    try:
        rows = execute_query("select 1 as ok")
        print("\n连接测试: 成功 %s" % rows)
    except Exception as e:
        print("\n连接测试: 失败 %s" % e)
        sys.exit(1)
