# -*- coding: utf-8 -*-
import cProfile, io, os, pstats, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'data'))
from backtest.engine import run_backtest

t0 = time.time()
r = run_backtest('000009.SZ', 'grid_classic', '2018-01-01', '2026-06-30')
print("冷跑一次: %.1f 秒 excess=%.2f%%" % (time.time()-t0, r['excess']), flush=True)

pr = cProfile.Profile()
t0 = time.time()
pr.enable()
run_backtest('000009.SZ', 'grid_classic', '2018-01-01', '2026-06-30')
pr.disable()
print("profile 跑: %.1f 秒" % (time.time()-t0), flush=True)

s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
ps.print_stats(22)
out = s.getvalue()
io.open(os.path.join(HERE, '_prof.txt'), 'w', encoding='utf-8').write(out)
print(out[:3000])
