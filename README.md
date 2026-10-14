# QuantCordis v1.0.0 — a minimal, trustworthy kernel

**English** | [中文](README.zh-CN.md)

A minimal, trustworthy kernel for A-share quantitative research: fix the data foundation
first, then talk about strategy conclusions.

## What it solves

```
Conclusions in A-share quantitative research are often not reproducible — the root is
the data foundation:

  · Price breaks: 61 stocks still show magnitude breaks after 2016 (000568.SZ, 792x)
  · Non-positive prices: 48,217 rows across 717 stocks
  · Forward adjustment: every dividend recomputes history -> backtests not reproducible

Fix the foundation or every conclusion after it is built on sand.
```

## Scope: exactly two things

```
1. Data layer — goals: reproducible, auditable
   · Pull unadjusted prices and adjustment factors from xtdata, compute adjustment here
     Benefit: no dependence on the vendor's adjustment convention, and a jump in the
     factor means a break, which can be checked
   · Every row carries its source and fetch time, so it is traceable to the day it came in
   · Integrity checks must be able to fail (when they do, no data is emitted)

2. Backtest layer — answers exactly one question
   Which strategy has a positive excess return (beats buy-and-hold over the same window)
   · The criterion is excess, not absolute return
   · Windows whose data does not pass are refused, not "run now, judge later"
   · If nothing is found, say so plainly; never pick a flattering number

Explicitly not done:
   · No order placement
   · No dashboard (a UI does not affect a conclusion; it comes last)
   · No real money
```

## Layout

```
data/        data layer: fetch, store, audit
backtest/    backtest layer and built-in strategies
market/      market sentiment indicators
tools/       research tools (factor study, etc.)
docs/        design and research documents
```

## Documentation

```
Design
  DATA-LAYER-DESIGN.md    data layer: tables, field conventions, traceability
  BACKTEST-DESIGN.md      backtest layer: fill assumptions, costs, adjustment
  PRICE-CONVENTIONS.md    price conventions: unadjusted / forward / backward
  ADJUST-FORMULA.md       adjustment formula and how it is verified
  SERVICE-CONVENTION.md   ports and processes
  DECISIONS.md            design choices and trade-offs

Data
  PRICE-GAPS-FIXED.md     locating and fixing price breaks and magnitude jumps
  SCAN-NEW-DATA.md        new data sources and field availability
  STRATEGY-SCREEN.md      strategy screen: six strategies on 1056 symbols
  SLIPPAGE-SENSITIVITY.md slippage sensitivity: the sign flips from 19 stocks to 25

Research results
  FACTOR-STUDY.md         factor study method and criteria
  CROSS-SECTION-TEST.md   cross-sectional factor tests (IC, buckets, portfolio)
  NEUTRAL-TEST.md         neutralisation tests
  OOS-TEST.md             out-of-sample tests
  STYLE-VS-ARBITRAGE.md   style exposure vs true excess
  FUNDAMENTAL-TEST.md     fundamental factor tests
  PORTFOLIO-TEST.md       portfolio-level tests
  LIMIT-UP-TEST.md        limit-up and sentiment-style signals
  SENTIMENT-TIMING.md     sentiment timing strategy

Landscape
  MARKET-LANDSCAPE.md     the A-share quant ecosystem
  OPEN-SOURCE-STACK.md    usable open-source stacks
  VNPY-ASSESSMENT.md      the VeighNa route

Roadmap
  ROADMAP.md              what comes next
```

## Quick start

```bash
# 1. Configure (copy the template, fill in your own database)
cp .env.example .env

# 2. Fetch data (one symbol as an example)
python data/bar_none.py --code 600519.SH --audit

# 3. Backtest
python backtest/engine.py --code 600519.SH --strategy ma20_hold \
    --start 2018-01-01

# 4. Factor study
python tools/factor_study.py ic
```

## Port convention

```
QuantCordis uses 7875
See docs/SERVICE-CONVENTION.md
```

## License

MIT, see LICENSE.
