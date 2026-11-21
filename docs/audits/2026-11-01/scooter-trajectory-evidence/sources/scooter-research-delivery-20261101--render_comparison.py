"""Render measured optimizer samples; no smoothing or synthetic poses."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='2')
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
sys.path.insert(0, str(ROOT / '.local-pilot/route-analysis-python'))
import hashlib
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

RUN = ROOT / '.local-pilot/scooter-joint-ba-20261101-v3'
OUT = Path(__file__).parent
paths = [RUN/'data.npz', RUN/'review-comparison.json'] + [RUN/n/'fit.npz' for n in ('w0','w05','w2')]
def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
before = {str(p.relative_to(ROOT)):sha(p) for p in paths}
source = json.loads((ROOT/'.local-pilot/scooter-targeted-gap-20261101-v2/geometry-0.json').read_text())
rotation = np.array(source['cameras'][0]['camera_to_world'])[:,:3]
base = np.load(RUN/'data.npz')
centers = {'baseline':base['centers']}
for n in ('w0','w05','w2'):
    centers[n] = np.load(RUN/n/'fit.npz')['centers']
paths2d = {n:((value-base['centers'][0])@rotation)[:,[0,2]] for n,value in centers.items()}
allxy = np.vstack(list(paths2d.values()))
low,high = allxy.min(0),allxy.max(0)
middle = (low+high)/2
span = float((high-low).max())*1.14
metrics = json.loads((RUN/'review-comparison.json').read_text())['cases']
plt.rcdefaults()
plt.rcParams.update({'font.family':'Segoe UI','font.size':10,'text.color':'#e6edf5',
    'axes.labelcolor':'#9dacc0','xtick.color':'#75899f','ytick.color':'#75899f',
    'axes.edgecolor':'#293c51','savefig.facecolor':'#091322','figure.facecolor':'#091322'})
fig,axs = plt.subplots(2,2,figsize=(15,11.6),dpi=130)
fig.subplots_adjust(left=.065,right=.97,bottom=.13,top=.80,wspace=.13,hspace=.34)
fig.text(.065,.958,'SPHERE  /  ZAEZD888  /  ПРОВЕРКА ГЕОМЕТРИИ',color='#4edbce',fontsize=11,weight='bold')
fig.text(.065,.914,'Гладкая линия ещё не означает правильный маршрут',fontsize=22,weight='bold')
fig.text(.065,.88,'166 исходных ракурсов · общие оси и масштаб · вращения и калибровка фиксированы',color='#9dacc0',fontsize=12)
titles = {'baseline':'Исходная модель','w0':'Контроль · без временного штрафа',
          'w05':'Штраф изменения скорости · 0,5','w2':'Штраф изменения скорости · 2'}
for ax,(name,xy) in zip(axs.flat,paths2d.items()):
    ax.set_facecolor('#0d1d30')
    ax.set_aspect('equal',adjustable='box')
    ax.set_xlim(middle[0]-span/2,middle[0]+span/2)
    ax.set_ylim(middle[1]-span/2,middle[1]+span/2)
    ax.grid(True,color='#25384b',alpha=.65,linewidth=.6)
    seg = np.stack([xy[:-1],xy[1:]],axis=1)
    lc = LineCollection(seg,cmap='winter',linewidth=2.0,zorder=3)
    lc.set_array(np.linspace(0,1,len(seg)))
    ax.add_collection(lc)
    ax.scatter(*xy.T,s=6,c='#81e9e3',zorder=4,linewidths=0)
    ax.scatter(*xy[0],s=55,c='#0d1d30',edgecolor='#e6edf5',linewidth=1.8,zorder=5)
    ax.scatter(*xy[-1],s=50,c='#ffb267',marker='x',linewidth=1.8,zorder=5)
    ax.set_title(titles[name],loc='left',pad=16,fontsize=13,weight='bold')
    ax.set_xlabel('X первого ракурса · условные единицы')
    ax.set_ylabel('Z первого ракурса')
    m=metrics[name]['heldout']
    state = 'ИСХОДНИК УЖЕ ВИДЕЛ ВСЕ НАБЛЮДЕНИЯ' if name=='baseline' else ('ЛИМИТ ВЫЧИСЛЕНИЙ · НЕ СОШЛОСЬ' if name=='w2' else 'СХОДИМОСТЬ ПО ftol')
    ax.text(0,1.01,state,transform=ax.transAxes,fontsize=7.6,color='#ffb267' if name in ('baseline','w2') else '#8ca6ba')
    text = f'Медиана / P95: {m["median_px"]:.3f} / {m["p95_px"]:.3f} px'
    ax.text(.03,.035,text,transform=ax.transAxes,color='#e6edf5',fontsize=10,
            bbox={'facecolor':'#091322','edgecolor':'#293c51','boxstyle':'round,pad=.5'})
fig.text(.065,.075,'○ начало   × последний ракурс   ·   Отрезки соединяют оценённые центры камер; междукадровое движение не восстановлено.',fontsize=10,color='#9dacc0')
fig.text(.065,.047,'Для w=0 / 0,5 / 2: 13 493 fit + 4 132 отложенных наблюдения. Их исходные позы уже использовали эти данные.',fontsize=10,color='#9dacc0')
fig.text(.065,.022,'Это проекция X/Z, не карта дороги. Независимой проверки поз и метрического масштаба нет. Для управления не принято.',fontsize=10,color='#ffb267')
fig.savefig(OUT/'quality-comparison.png')
plt.close(fig)
assert before == {str(p.relative_to(ROOT)):sha(p) for p in paths}
(OUT/'render-receipt.json').write_text(json.dumps({'source_hashes':before,'source_unchanged':True,
    'output_sha256':sha(OUT/'quality-comparison.png'),'physical_actions':0,
    'pose_interpolation':False,'diagnostic_only':True},indent=2),encoding='utf-8')
