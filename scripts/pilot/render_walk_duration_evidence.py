"""Render measured live/replay timing evidence; never sends game input."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main():
    from PIL import Image, ImageDraw, ImageFont

    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--benchmark',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('new_output_required')
    if any(p.stat().st_size>4*1024**2 for p in (args.report,args.benchmark)):raise ValueError('input_quota')
    raw=args.report.read_bytes();report=json.loads(raw);bench=json.loads(args.benchmark.read_bytes())
    if report['schema']!='sphere-walk-summary-v1' or bench['schema']!='sphere-recorded-game-encoder-v1':raise ValueError('schema')
    rows=report['observations'];totals=report['stageSummary']
    args.output.mkdir(parents=True)
    image=Image.new('RGB',(1800,1270),'#081321');draw=ImageDraw.Draw(image)
    def font(size,bold=False):
        return ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',size)
    def text(x,y,value,size=21,color='#a5b9cd',bold=False):draw.text((x,y),str(value),font=font(size,bold),fill=color)
    def panel(x,y,w,h):draw.rounded_rectangle((x,y,x+w,y+h),radius=18,fill='#101f30',outline='#29435b',width=2)
    def line(points,color,width=3):
        if len(points)>1:draw.line(points,fill=color,width=width)
    text(52,32,'SPHERE  /  LIVE ROUTE  /  РАЗБОР ПРОГОНА',19,'#59dbc6',True)
    text(52,72,'Остановки: измерения отдельно от исправлений',39,'#f0f6ff',True)
    text(52,128,'Реальный прогон walk_live_v6 · Kakaska228 · лимит сработал на 60-й секунде',23)
    cards=[('ОТВЕТЫ ЛОКАЛИЗАЦИИ',str(report['observationCount']),'За весь запуск; сохранена часть выборок'),
           ('ПРИМЕНЁННОЕ ДВИЖЕНИЕ',f"{max(r.get('motionSeconds')or 0 for r in rows):.2f} с",'По обратной связи стика; не метры пути'),
           ('ПРОГРЕСС ПРИ ОСТАНОВКЕ',f"{100*max(r.get('progress')or 0 for r in rows):.1f}%",'По восстановленной дуге; не факт прибытия')]
    for i,(label,value,note)in enumerate(cards):
        x=52+i*574;panel(x,183,552,139);text(x+22,198,label,17,'#86a4c1',True);text(x+22,223,value,39,'#eaf7ff',True);text(x+22,282,note,18)
    panel(52,347,1128,432);text(76,368,'Как менялся путь в сохранённых выборках',26,'#f0f6ff',True)
    text(76,408,f"{len(rows)} из {report['observationCount']} ответов · пробелы отчёта не интерполированы",19)
    x0,y0,w,h=112,468,1010,220
    for fraction in (0,.25,.5,.75,1):
        y=y0+h*(1-fraction);draw.line((x0,y,x0+w,y),fill='#294057');text(65,y-12,f'{fraction*100:g}%',17)
    for sec in range(0,61,10):
        x=x0+w*sec/60;draw.line((x,y0,x,y0+h),fill='#20384f');text(x-10,y0+h+12,str(sec),17)
    previous=None
    for row in rows:
        if row.get('progress')is None:previous=None;continue
        p=(x0+w*min(60,row['elapsedMs']/1000)/60,y0+h*(1-row['progress']))
        if previous and row['elapsedMs']-previous[0]<=450:line([previous[1],p],'#24cee2')
        draw.ellipse((p[0]-2,p[1]-2,p[0]+2,p[1]+2),fill='#24cee2')
        previous=(row['elapsedMs'],p)
    text(1010,731,'Время, с',17)
    panel(1204,347,544,432);text(1228,368,'Редкие задержки важнее среднего',23,'#f0f6ff',True)
    entries=[('JPEG · живой запуск',totals['encoder_jpeg']['maxDurationMs'],'#ffb968'),
             ('HTTP · живой запуск',totals['http']['maxDurationMs'],'#8b9fff'),
             ('JPEG · изолированный WebRTC',max(c['maximum']for c in bench['cases']),'#59dbc6')]
    for i,(label,ms,color)in enumerate(entries):
        y=421+i*83;text(1228,y,label,19);text(1640,y,f'{ms:.0f} мс',20,color,True)
        draw.rounded_rectangle((1228,y+34,1228+460*min(ms,500)/500,y+47),radius=5,fill=color)
    text(1228,684,'Порог свежести: 250 мс',19,'#ffb968',True)
    text(1228,716,'Тест WebRTC не воспроизводит всю',18);text(1228,742,'нагрузку пользовательской страницы.',18)
    panel(52,803,1696,195);text(76,823,'Поставлено в walk_live_v7',27,'#f0f6ff',True)
    text(76,868,'01  Длительность по записи',22,'#59dbc6',True);text(76,907,'Для 50,35 с записи — до 282 с',21);text(76,940,'Общий предел: 10 минут',19)
    text(640,868,'02  Возврат после скрытия',22,'#59dbc6',True);text(640,907,'Закрытие ввода → новые кадры',21);text(640,940,'→ узнавание → новый сеанс',19)
    text(1204,868,'03  Спокойная схема',22,'#59dbc6',True);text(1204,907,'Последняя измеренная точка: 1 с',21);text(1204,940,'Пунктир; права на движение нет',19)
    text(52,1030,'Изолированный браузерный тест',26,'#f0f6ff',True)
    text(52,1072,f"H.264 WebRTC · {bench['geometry'][0]} × {bench['geometry'][1]} · {sum(c['samples'] for c in bench['cases'])} кодирований · Android-команд: 0",22)
    text(52,1110,'Обычный контекст и willReadFrequently: ни одного кодирования дольше 250 мс.',21)
    text(52,1146,'Настройка production-кодировщика не менялась: устойчивое преимущество не показано.',21)
    text(52,1200,'Полный автономный проход после обновления ещё не проверен. График не доказывает метрическую точность.',20,'#ffcc8d')
    image.save(args.output/'live-duration-evidence.png')
    evidence=dict(schema='sphere-walk-duration-board-v1',physicalActions=0,reportSha256=hashlib.sha256(raw).hexdigest(),
        benchmarkSha256=hashlib.sha256(args.benchmark.read_bytes()).hexdigest(),wholeRunReplies=report['observationCount'],
        retainedRows=len(rows),motionSeconds=max(r.get('motionSeconds')or 0 for r in rows),
        stopReason=report['stopReason'],stopProgress=max(r.get('progress')or 0 for r in rows),liveCompletionVerified=False)
    (args.output/'board.json').write_text(json.dumps(evidence,indent=2),'utf-8')
    print(json.dumps(evidence))


if __name__=='__main__':main()
