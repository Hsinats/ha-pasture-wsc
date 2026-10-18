"""Illustrative sensitivity experiments using the repository's actual engine."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import matplotlib.pyplot as plt
from pasture_wsc.model import calculate, SoilIndex, MoistureMode

OUT = Path(__file__).resolve().parents[1] / 'outputs'
OUT.mkdir(exist_ok=True)
soil = SoilIndex(.47, 'Illustrative assumed wi', True, True)
mode = MoistureMode.DECREASING
def run(temps, radiation):
    total = 0
    values = []
    for t, r in zip(temps, radiation):
        total += calculate(13, float(t), float(r), soil=soil, mode=mode, scenario=True).development
        values.append(calculate(13, float(t), float(r), total, soil, mode, scenario=True).experimental_wsc)
    return np.array(values)

days = np.arange(1, 46)
t = np.full(45, 15.)
r = np.full(45, 16.)
r[14:17] = 4.
truth = run(t, r)
clear = run(t, np.full(45, 16.))
biased = t.copy(); biased[14:17] += 4
tbias = run(biased, r)
fig, axes = plt.subplots(3, 1, figsize=(10, 11), constrained_layout=True)
colors = ['#2366aa', '#cb6918', '#7561a8']
for ax in axes:
    ax.set_ylabel('Experimental WSC (% dry matter)')
    ax.grid(alpha=.18)
    ax.spines[['top','right']].set_visible(False)
axes[0].set_title('Uncertain cut date: same weather, different accumulated development', loc='left')
constant = run(np.full(59,15.),np.full(59,16.))
x = np.arange(14,46)
for age, label, c, ls in [(-7,'Cut 7 days later',colors[1],'--'),(0,'Nominal cut date',colors[0],'-'),(7,'Cut 7 days earlier',colors[2],':')]:
    axes[0].plot(x,constant[x+age-1],label=label,color=c,ls=ls,lw=2)
axes[0].set_xlabel('Days since nominal cut date')
axes[1].set_title('Cloud gap: three cloudy days incorrectly filled as clear', loc='left')
axes[1].plot(days,truth,label='Cloudy days retained',color=colors[0],lw=2)
axes[1].plot(days,clear,label='Cloudy days filled as clear',color=colors[1],ls='--',lw=2)
axes[2].set_title('Temperature gap: afternoon-only mean is 4°C too warm for three days', loc='left')
axes[2].plot(days,truth,label='Full-day temperature',color=colors[0],lw=2)
axes[2].plot(days,tbias,label='Biased temperature fill',color=colors[1],ls='--',lw=2)
for ax in axes[1:]:
    ax.axvspan(15,17,color=colors[2],alpha=.12)
    ax.set_xlabel('Days since cut')
for ax in axes:
    ax.legend(frameon=False,loc='best')
fig.suptitle('Missing-history scenarios — current model equations, synthetic weather',fontsize=15)
fig.supxlabel('Assumptions: daylength 13 h; mean temperature 15°C; wi 0.47; radiation 16 MJ/m²/day,\nexcept cloudy days 15–17 at 4 MJ/m²/day. Illustrations, not a pasture forecast.',fontsize=10)
fig.savefig(OUT/'history-scenarios.png',dpi=170)
print('Cloud gap maximum WSC difference:', round(float(np.max(clear-truth)),3), 'percentage points')
print('Temperature difference on day 17:',round(float(tbias[16]-truth[16]),3))
print('Temperature difference on day 45:',round(float(tbias[-1]-truth[-1]),3))
print(OUT/'history-scenarios.png')
