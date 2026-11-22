"""Measured, unaccepted diagnostic model, with its real source frames."""
from pathlib import Path
import hashlib
import json
import sys

root = Path.cwd()
sys.path.insert(0, str(root))
sys.path.append(str(root/'.local-pilot/route-analysis-python'))
from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
initialize_route_cpu_runtime()
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import FancyBboxPatch
from PIL import Image

refined = '--refined' in sys.argv
targeted = '--targeted' in sys.argv
folder = root/('.local-pilot/scooter-targeted-gap-20261101-v2' if targeted else '.local-pilot/scooter-stage-global-focal-20261101' if refined else '.local-pilot/scooter-stage-global-20261101')
geometry_path = folder/'geometry-0.json'
g = json.loads(geometry_path.read_bytes())
q = json.loads((folder/'report.json').read_bytes())['models'][0]
comparison = json.loads((folder/'comparison.json').read_bytes())['models'][0]
cameras = g['cameras']
assert len(cameras) == (166 if targeted else 163) and not q['route_admissible']
assert comparison['new']['test_factor4'] == (5 if targeted else 18 if refined else 48)
xyz = np.asarray([c['center'] for c in cameras])
R = np.asarray(cameras[0]['camera_to_world'])[:, :3]
path = (xyz-xyz[0])@R
points = (np.asarray(g['points'])[:, :3]-xyz[0])@R
times = np.asarray([c['ticks_90k']/90000 for c in cameras])
low, high = path[:, [0,2]].min(0), path[:, [0,2]].max(0)
margin = np.maximum((high-low)*.20, .2)
low -= margin
high += margin
visible = ((points[:, [0,2]] >= low)&(points[:, [0,2]] <= high)).all(1)

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,
 'figure.facecolor':'#081321','axes.facecolor':'#0c1b2b','axes.edgecolor':'#2c4055',
 'text.color':'#edf5ff','axes.labelcolor':'#92a9bf','xtick.color':'#92a9bf',
 'ytick.color':'#92a9bf','grid.color':'#203448'})
fig = plt.figure(figsize=(15,11), dpi=150)
fig.text(.045,.958,'SPHERE   /   ZAEZD888   /   ПОЛНЫЙ ДИАГНОСТИЧЕСКИЙ ПРОГОН',
         fontsize=10,color='#5ad9cd',weight='bold')
title = 'zaezd888: добавлены 3 исходных кадра' if targeted else 'Новый прогон: маршрут и проверка по HUD' if refined else 'Больше ориентиров — траектория пока хуже'
fig.text(.045,.914,title,fontsize=24,weight='bold')
fig.text(.045,.875,'Реальные камеры и 3D-точки · 0–35,493 с · исходное видео не изменено',
         fontsize=11,color='#99afc4')
ax = fig.add_axes([.065,.32,.58,.49])
ax.scatter(points[visible,0],points[visible,2],s=.65,c='#526c86',alpha=.4,rasterized=True)
segments = np.stack([path[:-1,[0,2]],path[1:,[0,2]]],axis=1)
cmap = LinearSegmentedColormap.from_list('route',['#47a8ff','#27dacb','#c2ef8a'])
lc = LineCollection(segments,cmap=cmap,norm=Normalize(0,times[-1]),linewidth=2.6,zorder=4)
lc.set_array(times[:-1]); ax.add_collection(lc)
ax.scatter(path[0,0],path[0,2],s=65,facecolors='#0c1b2b',edgecolors='white',linewidth=1.7,zorder=6)
ax.scatter(path[-1,0],path[-1,2],s=62,marker='x',c='#eead61',linewidth=1.8,zorder=6)
by_name = {c['image']: i for i,c in enumerate(cameras)}
bad = np.asarray([by_name[r['image']] for r in q['motion']['rapid_reversals']],dtype=int)
bad = bad[(bad >= 0)&(bad < len(path))]
ax.scatter(path[bad,0],path[bad,2],s=40,facecolors='none',edgecolors='#eead61',linewidth=.9,zorder=5)
for sec in (0,5,10,15,20,25,30,35.493):
    i = int(np.argmin(abs(times-sec)))
    ax.annotate(f'{times[i]:.1f} с',(path[i,0],path[i,2]),xytext=(7,7),textcoords='offset points',
                color='#eff7ff',fontsize=8,bbox={'boxstyle':'round,pad=.22','fc':'#102439','ec':'none','alpha':.9})
ax.set(xlim=(low[0],high[0]),ylim=(low[1],high[1]),xlabel='Вправо · условные единицы',ylabel='Вперёд · условные единицы')
ax.set_aspect('equal',adjustable='box'); ax.grid(alpha=.5)
ax.set_title('Путь камеры и ориентиры в осях первого ракурса',loc='left',pad=15,fontsize=12,weight='bold')

def card(y,label,value,detail,color='#edf5ff'):
    box = FancyBboxPatch((.695,y),.255,.081,boxstyle='round,pad=.008,rounding_size=.009',
                         transform=fig.transFigure,fc='#102237',ec='#2a435c')
    fig.add_artist(box)
    fig.text(.712,y+.058,label,fontsize=8,color='#8eaac2',weight='bold')
    fig.text(.712,y+.026,value,fontsize=20,color=color,weight='bold')
    fig.text(.712,y+.006,detail,fontsize=8,color='#9fb2c7')
card(.725,'ВОССТАНОВЛЕННЫЕ РАКУРСЫ',f'{len(cameras)} / {len(cameras)}','Один компонент, максимальный шаг 0,266 с')
card(.619,'3D-ТОЧКИ В МОДЕЛИ',f'{q["points"]:,}'.replace(',',' '),
     f'Ошибка {q["reprojection_px"]:.3f} px · экспорт {len(points):,}'.replace(',',' '))
card(.513,'ЭВРИСТИЧЕСКИЕ СИГНАЛЫ',f'{len(bad)} / {len(q["motion"]["speed_outliers"])}',
     'Скачки / выбросы; это не число поворотов', '#efb368')
card(.407,'ОТЛОЖЕННЫЕ HUD-ИНТЕРВАЛЫ',f'{comparison["new"]["test_factor4"]} / 60',
     f'Расхождение >4×; у baseline было {comparison["baseline"]["test_factor4"]} / 60','#efb368')
fig.text(.70,.36,'РЕЗУЛЬТАТ НЕ ПРИНЯТ ДЛЯ УПРАВЛЕНИЯ',fontsize=9,color='#efb368',weight='bold')
focal = cameras[0]['intrinsics']['fx']
fig.text(.70,.328,(f'Общий фокус {focal:.2f} px · калибровка не подтверждена' if refined or targeted else 'Глобальное позиционирование: NO_CONVERGENCE')+'\nМетры, дорожная поверхность и точность не доказаны.',
         fontsize=8,color='#a6b8ca',linespacing=1.7)
fig.text(.045,.278,'ПРОВЕРЯЕМ С ИСХОДНЫМИ КАДРАМИ',fontsize=9,color='#62d7d1',weight='bold')
frame_receipts=[]
for j,sec in enumerate((0,10,20,35.493)):
    i=int(np.argmin(abs(times-sec)))
    images_folder = folder/'prepared/images' if targeted else root/'.local-pilot/scooter-precise-hud-20261101/reconstruction/prepared/images'
    frame = images_folder/cameras[i]['image']
    a=fig.add_axes([.045+j*.233,.105,.215,.14])
    with Image.open(frame) as im: a.imshow(im)
    a.set_axis_off(); a.set_title(f'{times[i]:.3f} с · {cameras[i]["image"]}',loc='left',fontsize=8,color='#b3c4d5',pad=6)
    frame_receipts.append({'image':cameras[i]['image'],'ticks_90k':cameras[i]['ticks_90k'],
                           'sha256':hashlib.sha256(frame.read_bytes()).hexdigest()})
fig.text(.045,.065,f'Показано {int(visible.sum()):,} из {len(points):,} точек в пределах вида; все {len(cameras)} положений камеры сохранены.'.replace(',',' '),
         fontsize=8,color='#8fa5bb')
fig.text(.045,.037,'Схема не является картой дорог. HUD — наблюдение того же клипа, не независимая истина; масштаб подогнан по 65 обучающим интервалам.',
         fontsize=8,color='#8fa5bb')
output=root/'docs/audits/2026-11-01/assets'/('scooter-targeted-gap-result.png' if targeted else 'scooter-refined-focal-result.png' if refined else 'scooter-full-graph-result.png')
fig.savefig(output,dpi=150);plt.close(fig)
result={'schema':'sphere-scooter-figure-v1','source_geometry':str(geometry_path.relative_to(root)),
        'geometry_sha256':hashlib.sha256(geometry_path.read_bytes()).hexdigest(),'source_frames':frame_receipts,
        'figure':str(output.relative_to(root)),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'bytes':output.stat().st_size,'points_visible':int(visible.sum()),'points_total':len(points),
        'execution_qualified':False}
(folder/'figure-receipt.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
