# 可复用的开源栈（MIT / Apache）—— 核实


> → 核实结果: 可行，而且有一条与 QMT 同源的完整栈

---

## 一、许可核实（用 GitHub API 查，不凭印象）

| 项目 | 许可 | 星 | 能直接用吗 |
|---|---|---|---|
| [vnpy/vnpy](https://github.com/vnpy/vnpy) | MIT | 45,859 | 可以自由用改 |
| [vnpy/vnpy_xt](https://github.com/vnpy/vnpy_xt) | MIT | 75 | 迅投数据接口，与 QMT 同源 |
| [ruyisee/vnpy_qmt](https://github.com/ruyisee/vnpy_qmt) | Apache-2.0 | 118 | QMT 交易网关 |
| [microsoft/qlib](https://github.com/microsoft/qlib) | MIT | 49,352 | 因子库 + ML 工作流 |
| [akfamily/akshare](https://github.com/akfamily/akshare) | MIT | 22,925 | 补充数据（龙虎榜/资金流）|
| [AI4Finance/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | MIT | 16,638 | 强化学习（暂不需要）|
| [wangpage/quant-ashare](https://github.com/wangpage/quant-ashare) | NOASSERTION | 28 | 只能学习参考，不能复制代码 |

 关于最后一行（要守住的界线）:
```
它 README 里写 MIT 但GitHub 识别不出许可（NOASSERTION）
→ 法律上不确定 → 只读它的思路，不复制它的代码
→ 而它的思路很有价值（重叠样本 t 虚高 · A股独有因子清单）
 → 思路不受版权保护 代码才受
```

## 二、 核心发现: vnpy_xt 与我们的数据源同源

```
 vnpy_xt 的 README 原文:
 「基于迅投 XtQuant 封装开发的实时行情和数据服务接口」
 → XtQuant 就是我们正在用的 xtdata / xttrader
 两种连接方式:
 ① Token 连接（迅投研服务平台 xuntou.net 需申请/购买）
 ② 客户端连接 —— 「需保持迅投客户端的运行」
 → 这正是我们在做的: XtMiniQmt.exe 在跑
 它要求xtquant 包放 site_packages → 我们也是这么做的
 支持范围: 股票 · 基金 · 债券 · ETF期权（上交所/深交所）+ 期货（六个交易所）
 但它只有数据 → 交易要另配 vnpy_qmt 或直接用 xtquant
```


```
 「重写是几个月的工程」这个估计 —— 那是假设从零写
→ 用 VeighNa 就不用从零写:
 · 事件引擎（event engine）· 风控模块
 · 图形界面 —— 这正是用户要的"有图"
 · 定时任务 / 数据引擎 / 交易网关 / 策略模板
 · 45,859 星 · MIT → 长期维护有保障
```

## 四、 但不是"一夜切换"（诚实评估）

```
 迁移的工程量真实存在:
 · 13 个策略要包装成 vnpy 的 Strategy 模板
 （好在它们是纯函数 (code, market, capital) → 包装不难）
 · 数据要迁移（新表结构带复权因子）
 · 现有看板/风控逻辑要重建或对接
 · 需要学习 vnpy 的架构与文档
 → → 分阶段，不是一次切换:

 阶段 1（低风险）: 数据源验证
 用 vnpy_xt 读一遍行情 → 与我们 xtdata 的结果逐条对照
 判据: 同一天同一只票的 close 完全一致
 阶段 2（中风险）: 因子与研究
 参考 qlib 的因子库与工作流 → 补我们的缺口
 数据仍用我们自己的表
 阶段 3（高风险 要用户批准）: 引擎
 评估把引擎换成 VeighNa → 它解决我们的"收盘后跳过"缺陷
 且自带图形界面
 但这条影响真实交易流程 → 先问用户
```

## 五、 我们能用它们补哪些缺口（对照 MARKET-LANDSCAPE.md 的 11 层）

| 缺口 | 谁能补 | 许可 |
|---|---|---|
| 数据可复现（复权因子）| 自己建表 + vnpy_xt 取数 | MIT |
| 因子库（只有 4 个）| qlib（Alpha158/360）| MIT |
| 标签工程 / 停牌一字板屏蔽 | 参考 quant-ashare 的思路 | 只学思路 |
| A股独有因子（涨停连板 · 龙虎榜）| akshare 提供数据 · 因子要自己写 | MIT |
| Barra 中性化 | qlib 有行业/风格暴露 | MIT |
| 冲击成本 / 滑点 | 参考 quant-ashare 的公式（Almgren-Chriss 公开算法）| 算法无版权 |
| 图形界面（用户要的）| VeighNa 自带 | MIT |
| 收盘后跳过（架构缺陷）| VeighNa 的事件驱动 + 定时任务 | MIT |

## 六、下一步建议（按风险从低到高）

```
① 先做零风险的: 用 vnpy_xt 读一次行情，与我们 xtdata 结果对照
 → 判据: 完全一致 → 证明这条路的数据层可用
 → 花时间少 · 不改任何现有东西
② 再决定: 要不要把研究层逐步迁到 qlib 的写法
③ 最后谈: 引擎是否换 VeighNa → 要用户批准
```
