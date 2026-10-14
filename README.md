# QuantCordis v1.0.0 —— 最小可信内核

A 股量化研究的最小可信内核：先修数据地基，再谈策略结论。

## 它解决什么

```
A 股量化研究的结论往往不可复现 —— 根子在数据地基:

  · 价格断裂: 2016 年后仍有 61 只有量级断裂（000568.SZ 792 倍）
  · 非正价格: 48,217 行 · 717 只
  · 前复权: 每次分红都重算历史 → 回测不可复现

数据地基不修，后面所有结论都建在沙子上。
```

## 它的边界：只做两件事

```
① 数据层 —— 目标: 可复现 + 可审计
   · 从 xtdata 拉不复权价与复权因子，自己算复权
     好处: 不依赖数据源的复权口径；因子突变即断裂，可查
   · 每条记录带来源与抓取时间，可追溯到哪天抓的
   · 完整性检查必须能失败（不通过就拒绝出数）

② 回测层 —— 只回答一个问题
   哪个策略的超额为正（跑赢同期买入持有）
   · 判据是超额，不是绝对收益
   · 数据不过关的区间直接拒绝回测，而不是"跑出来再说"
   · 找不到就如实报告找不到，绝不挑一个好看的数

不做（明确排除）:
   · 不做下单
   · 不做页面（界面不影响结论，排在最后）
   · 不碰真实资金
```

## 目录

```
data/        数据层: 拉取 · 落库 · 审计
backtest/    回测层与内置策略
market/      市场情绪指标
tools/       研究工具（因子研究等）
docs/        设计与研究文档
```

## 文档

```
设计
  DATA-LAYER-DESIGN.md    数据层: 表结构 · 字段口径 · 来源可追溯
  BACKTEST-DESIGN.md      回测层: 成交假设 · 成本 · 复权口径
  PRICE-CONVENTIONS.md    价格口径: 不复权 / 前复权 / 后复权怎么用
  ADJUST-FORMULA.md       复权公式与验证方法
  SERVICE-CONVENTION.md   服务端口与进程约定
  DECISIONS.md            设计选择与取舍

数据
  PRICE-GAPS-FIXED.md     价格断裂与量级问题的定位与修法
  SCAN-NEW-DATA.md        新数据源与字段可用性
  SLIPPAGE-SENSITIVITY.md 滑点敏感性: 样本从 19 只换到 25 只，符号翻转

研究结论
  FACTOR-STUDY.md         因子研究方法与判据
  CROSS-SECTION-TEST.md   横截面因子检验（IC · 分层 · 组合）
  NEUTRAL-TEST.md         中性化检验
  OOS-TEST.md             样本外检验
  STYLE-VS-ARBITRAGE.md   风格暴露与真超额
  FUNDAMENTAL-TEST.md     基本面因子检验
  PORTFOLIO-TEST.md       组合层检验
  LIMIT-UP-TEST.md        涨停与情绪类信号检验
  SENTIMENT-TIMING.md     情绪择时策略

对标
  MARKET-LANDSCAPE.md     A 股量化生态全景
  OPEN-SOURCE-STACK.md    可用的开源栈评估
  VNPY-ASSESSMENT.md      VeighNa 路线评估

路线
  ROADMAP.md              未来计划
```

## 快速开始

```bash
# 1. 配置（复制模板并填自己的库）
cp .env.example .env

# 2. 拉数据（以一只票为例）
python data/bar_none.py --code 600519.SH --audit

# 3. 回测
python backtest/engine.py --code 600519.SH --strategy ma20_hold \
    --start 2018-01-01

# 4. 因子研究
python tools/factor_study.py ic
```

## 端口约定

```
QuantCordis 用 7875
详见 docs/SERVICE-CONVENTION.md
```

## 许可

MIT，见 LICENSE。
