from pathlib import Path
import csv,json,sys,hashlib
root=Path.cwd();sys.path.insert(0,str(root));sys.path.append(str(root/'.local-pilot/route-analysis-python'))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
folder=root/'.local-pilot/scooter-hud-heading-20261101'
rows=list(csv.DictReader((folder/'headings.csv').open(encoding='utf-8')))
intervals=json.loads((folder/'intervals.json').read_bytes())
r=json.loads((folder/'report.json').read_bytes())
t=np.array([int(x['ticks_90k'])/90000 for x in rows])
f=np.array([float(x['heading_forward_deg']) for x in rows]);b=np.array([float(x['heading_reverse_deg']) for x in rows])
speeds={int(x['source_index']):float(x['accepted_hud_kmh_or_empty']) for x in rows if x['accepted_hud_kmh_or_empty']}
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'figure.facecolor':'#091421',
 'axes.facecolor':'#102135','axes.edgecolor':'#31465d','text.color':'#eaf4ff','axes.labelcolor':'#9eb2c7',
 'xtick.color':'#9eb2c7','ytick.color':'#9eb2c7','grid.color':'#2c4258'})
fig,(a,c)=plt.subplots(2,1,figsize=(14,8),sharex=True,gridspec_kw={'height_ratios':[1.3,1]})
fig.subplots_adjust(top=.73,bottom=.18,left=.08,right=.95,hspace=.24)
fig.text(.08,.94,'SPHERE  /  ZAEZD888  /  ВСЕ 901 КАДР',fontsize=10,color='#5bdbce',weight='bold')
fig.text(.08,.885,'Проверка прямого и обратного прохода',fontsize=23,weight='bold')
fig.text(.08,.817,'0,035°  медиана цикла соседних вращений     ·     82,22%  времени поддержано HUD',fontsize=12,color='#acd8ed')
a.plot(t,f,c='#2bd4dd',lw=2,label='Прямой проход')
a.plot(t,b,c='#eaae6a',lw=1.6,ls='--',label='Обратный · совмещён по первому кадру')
a.set_ylabel('Ориентация оптической оси, °');a.set_ylim(-10,170);a.grid(alpha=.5)
a.legend(loc='upper left',facecolor='#102135',edgecolor='#31465d',labelcolor='#d2e2ee',fontsize=9)
for v in intervals:
    if not v['speed_supported']:continue
    i,j=v['frame_a'],v['frame_b']
    c.plot([v['start_seconds'],v['end_seconds']],[speeds[i],speeds[j]],c='#4dd8b6',lw=1.5)
    a.axvspan(v['start_seconds'],v['end_seconds'],color='#42be99',alpha=.035,lw=0)
indices=np.array(sorted(speeds));c.scatter(t[indices],[speeds[int(i)] for i in indices],c='#97e8c2',s=4,zorder=4)
c.set(xlabel='Время исходной записи, с',ylabel='Скорость из HUD, game km/h',xlim=(0,t[-1]),ylim=(0,100));c.grid(alpha=.5)
fig.text(.08,.095,'Перемещение по CalfVO между направлениями не согласовано; цельная карта из этих кривых не получена.',fontsize=10,color='#eaae6a')
fig.text(.08,.055,'HUD: 29,182 с поддержано, 6,311 с неизвестно. Камера ≠ подтверждённый курс скутера; физический масштаб не проверен.',fontsize=9,color='#9eb2c7')
output=root/'docs/audits/2026-11-01/assets/scooter-forward-reverse-heading.png';fig.savefig(output,dpi=150);plt.close(fig)
receipt={'figure':str(output.relative_to(root)),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'bytes':output.stat().st_size,
 'source_files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [folder/'headings.csv',folder/'intervals.json',folder/'report.json']},
 'execution_qualified':False,'physical_metric_verified':False}
(folder/'figure-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps(receipt))
