# VeighNa（vn.py）评估 —— 读源码的结论

> 目的: 判断「换 VeighNa」这条路值不值得走
> 方法: 读源码 不装包 不改环境 （零风险 · MIT 可自由读）

---

## 一、它的结构（GitHub API 实测）

```
vnpy/
├── event/engine.py 148 行 · 4.3KB ← 事件引擎（极简）
├── chart/ 6 文件
│ ├── widget.py 17.5KB ← 完整图表控件 用户要的"有图"
│ ├── item.py 10.2KB ← K线 / 线 / 柱等图形元素
│ └── axis.py · base.py · manager.py
├── trader/
│ ├── engine.py 28.5KB ← 主引擎（含策略模板）
│ ├── utility.py 41.6KB ← BarGenerator / ArrayManager（K线合成 · 指标缓存）
│ ├── object.py 10.5KB ← 标准数据结构（TickData/BarData/OrderData/TradeData）
│ ├── converter.py 16.0KB ← 数据转换
│ ├── wechat.py 9.1KB ← 微信推送现成的
│ ├── gateway.py 7.8KB ← 交易网关基类
│ ├── database.py 3.7KB ← 数据库抽象
│ ├── datafeed.py 2.1KB ← 数据服务抽象（vnpy_xt 接在这里）
│ ├── optimize.py 8.8KB ← 参数优化
│ └── ui/ ← 界面模块
└── alpha/lab.py 16.4KB ← 研究实验室（+ dataset/ model/ strategy/）
```

## 二、 事件引擎（148 行，读完）

```python
EVENT_TIMER = "eTimer"

class EventEngine:
 def __init__(self, interval: int = 1):
 self._queue = Queue
 self._thread = Thread(target=self._run) # 消费事件
 self._timer = Thread(target=self._run_timer) # 发定时事件
 self._handlers = defaultdict(list) # 按类型分发

 def _run_timer(self):
 while self._active:
 sleep(self._interval)
 self.put(Event(EVENT_TIMER)) # 每秒发一个 eTimer

 def register(self, type, handler): ... # 按类型注册
 def register_general(self, handler): ... # 监听所有类型（日志/监控）
```

### → 它为什么不会有我们那个缺陷

```
 它的定时器每秒发事件 → 处理器自己判断该不该做事
 策略由Bar 事件驱动 → 收到"日线收盘"事件就处理
 整个架构里没有"现在是不是盘中"这个判据
 → 而我们的引擎有: if not is_a_share_trading_hour: 跳过
 → 那个判据把 15:00 之后一起挡掉了 → 日K 策略永远算不出信号
→ → 这不是"补一个窗口"能比的 而是架构上不会错
```

## 三、 两条路的对比（诚实算账）

| | 方案 A: 在现有基础上改 | 方案 B: 换 VeighNa |
|---|---|---|
| 改动量 | 小（加收盘后窗口 · 几十行）| 大（策略包装 + 数据迁移 + 界面重建）|
| 缺陷性质 | 逻辑缺陷能修 | 架构上不会 |
| 会不会再犯 | △ 可能（同类判据别处也可能写宽）| 不会 |
| 图形界面 | 要自己写 | 自带 chart/ 模块 |
| 微信推送 | 要自己写 | 自带 wechat.py |
| K线合成 / 指标缓存 | 要自己写 | 自带 BarGenerator / ArrayManager |
| 维护 | 自己维护 | 45,859 星 + MIT → 社区维护 |
| 风险 | 低（改动小 · 可回退）| 中（要迁移 · 但可并行跑）|

## 四、 包装 13 个策略的工程量（实算）

```
 VeighNa 的策略模板是 CtaTemplate（on_bar / on_tick 回调）
 我们的策略是纯函数: strat_x(code, market, capital) -> {side, strategy, reason}
→ 包装方式（每个策略约 20-30 行）:

 class OurStrategy(CtaTemplate):
 def on_bar(self, bar):
 result = STRAT_FUNC(self.vt_symbol, self.am, self.capital)
 if result["side"] == "buy": self.buy(...)
 elif result["side"] == "sell": self.sell(...)

 · market → 用 ArrayManager（VeighNa 自带 接口是 get_recent_kline 的等价物）
 · code → 策略实例绑定合约
 · capital → 引擎注入

→ 13 个策略 ≈ 300-400 行包装代码 → 不大
 数据迁移: 新表结构（带复权因子）本来就要建 → 不算额外成本
```

## 五、我的判断（这是判断，不是感觉）

```
 推荐路线 B（换 VeighNa），但要并行走，不是切换:

 ① 阶段 1（低风险 立刻可做）:
 用 vnpy_xt 或直接读 vnpy 的 utility/object → 学它的数据结构与 K线合成
 → 用它重写我们自己的数据层（带复权因子）
 → 判据: 同一只票同一天 close 完全一致

 ② 阶段 2（中风险）:
 把 13 个策略包装成 CtaTemplate → 在 VeighNa 里回测
 → 判据: 同一 (策略,票,区间) 的净值曲线可复现
 （若不一致 → 说明有一边错了 这本身是价值）

 ③ 阶段 3（高风险 要用户批准）:
 用 VeighNa 跑模拟盘 → 与现有实现并排跑 → 对照一段时间
 → 只在新引擎行为被验证过之后 → 才谈实盘


```

## 六、 为什么推荐 B 而不只是"修 A"

```
 修 A 能解决今天这个缺陷
 但今天一天就发现了 5 个洞（dry_run 不建仓 · 资金基数污染 · 单票上限不看持仓 ·
 时段判断重复 · 收盘后跳过）
→ 洞的密度说明: 这套代码是多人多轮叠加的 → 修完一个还会有下一个
 而 VeighNa 是单一架构 + 45,859 星 + 十年迭代
 → 它的"没有这个缺陷"不是运气 是设计使然
 → 结论: 短期在现有基础上改，长期换 VeighNa，两者不冲突
```
