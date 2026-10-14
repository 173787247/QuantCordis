# 数据层设计 —— 实测立住的地基

> 目标: 可复现 + 可审计的行情数据
> 判据: 同一段区间跑两次结果完全一致 · 与数据源逐条对得上

---

## 一、 复权因子的来源找到了

```
 xtdata 的 get_divid_factors(code)→ DataFrame
 列: time · interest · stockBonus · stockGift · allotNum · allotPrice · gugai · dr
 → dr= 除权除息因子 = 我们需要的那个

 实测（600519.SH 贵州茅台 30 条记录）:
 20020725 interest=0.600 stockGift=0.1 dr=1.118279
 20040701 interest=0.300 stockGift=0.3 dr=1.311507
 20060519 interest=0.300 stockGift=1.0 dr=2.006365
 20240619 interest=30.876 dr=1.020716
 20241220 interest=23.882 dr=1.015637
 20250626 interest=27.673 dr=1.019649
 20251219 interest=23.957 dr=1.017028
 20260626 interest=28.02423 dr=1.023663
 字段含义（标准 A股 口径）:
 interest 每股派息（元）· stockBonus 每股送股 · stockGift 每股转增
 allotNum 每股配股 · allotPrice 配股价 · gugai 股改 · dr 除权除息因子
```

### 交叉验证（两条独立的路，同一个数）

```
 路 A: 分红表里 20260626 的 interest = 28.02423
 路 B: 几小时前我独立实测xtdata 的 front 与 none 的差额 = 28.02
 （当时原始记录:「06-25 之前差额恒定 28.02 → 28.02 = 每股分红」）
→ → 两条完全不同的路，得到同一个数
 → 这说明: ① 分红表可信 ② 我对 front 的理解正确
```


```
 曾有一种说法:「库里的负价格是库把前复权算坏了」
 实测更准确: xtdata 的 front 口径本身就产出负值
 · 600519.SH 于 2016-01-01 → 2026-06-30 的 front: 125 天 ≤ 0
 · 第一个: 20160104 = −87.8082
→ → 不是库算坏 是数据源的 front 就这样
 → 而这更强地支持了"只存 none"的决定
```

## 三、 被否定的假设（我原来想用 back/none）

```
 假设: 因子 = back / none （以为 back 是"乘累计因子"）
 实测: back/none 有 2,530 个不同取值，每个只出现 1 天
 → 不是阶梯常量 → 不是因子
 而且用它重建前复权 → 最大差 273 → 假设不成立
 → 若我直接按这个假设建表 → 整个数据层是错的
```

## 四、数据层设计（据此定下）

```
 存什么:
 ① bar_none 日K 不复权（open/high/low/close/volume/amount）
 来源: xtdata get_market_data_ex(dividend_type="none" )
 ② divid_factor 分红因子表（每只每次除权一行）
 来源: xtdata get_divid_factors(code)
 字段: code · ex_date · interest · stockBonus · stockGift ·
 allotNum · allotPrice · dr
 ③ trade_calendar 交易日历
 来源: xtdata get_trading_dates / get_holidays
 ④ st_history ST 历史（黑名单可自动化）
 来源: xtdata get_his_st_data
 ⑤ stock_info 合约信息（板块 · 上市日）
 来源: xtdata get_instrument_detail + get_stock_list_in_sector

 复权自己算（不落库 用时算 或落成视图）:
 后复权: price_back(t) = price_none(t) × Π(dr 对 t 之后的所有除权)
 前复权: price_front(t) = price_none(t) × Π(dr 对 t 之后) ÷ Π(全部 dr)
 → 两种视图从同一份 none 数据算出 → 一套数据，两种视图

 审计（能失败）:
 ① none 价必须全部 > 0 —— 实测 none 在茅台上有没有 ≤0 → 要逐股验
 ② 相邻两日比值 >5 或 <1/5 且前一日有成交 → 标断裂
 ③ 因子表单调性检查（dr 应当 > 0）
 ④ 两跑同一区间 → 结果完全一致（可复现）
```

## 五、 顺带发现（xtdata 还有 146 个接口）

```
 现在靠手写或没有的，它都有:
 · get_trading_calendar · get_holidays → 交易日历（含节假日）
 · get_his_st_data · download_his_st_data → ST 历史黑名单可自动化
 · get_stock_list_in_sector → 板块成分（行业规则精确化）
 · get_l2_order · get_l2_quote · get_l2_transaction → Level2
 · download_financial_data / get_financial_data → 财务数据
 · get_index_weight · get_ipo_info · get_instrument_detail
 注意: getDividFactors（驼峰）返回 None → 要用get_divid_factors
```

## 六、下一步（M1 里程碑）

```
① 建表（bar_none · divid_factor · trade_calendar · st_history）
② 拉一只票全历史（含分红）→ 与 xtdata 的 none 逐条对照
③ 自己算前复权 → 与 xtdata 的 front 对照
 → 注意: front 有 125 天 ≤ 0 → 只在 >0 的日子对照
④ 判据: 两跑同一区间 → 结果完全一致（库做不到这一条）
```
