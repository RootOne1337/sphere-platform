"""Summarize preserved live reports without extracting ZIPs or issuing input."""
import argparse
import collections
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import zipfile


def analyze(archive, since):
    result=[]
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist())>128 or sum(i.file_size for i in z.infolist())>64*1024**2:raise ValueError('walk_audit_zip_quota')
        for info in z.infolist():
            if info.file_size>512*1024:raise ValueError('walk_audit_report_quota')
            at=datetime(*info.date_time).timestamp()
            if at<since:continue
            raw=z.read(info);r=json.loads(raw);stages=r['stages'];obs=r['observations']
            timings={}
            for kind in ('jpeg','http','source_gap','long_task'):
                values=sorted(x['durationMs'] for x in stages if x['stage']==kind and 'durationMs' in x)
                if values:timings[kind]=dict(count=len(values),median=statistics.median(values),maximum=max(values))
            result.append(dict(id=r['id'],localTime=datetime.fromtimestamp(at).isoformat(),sha256=hashlib.sha256(raw).hexdigest(),
                stop=r['stopReason'],release=r['release'],observations=len(obs),
                durationMs=max((x['elapsedMs'] for x in obs),default=0),
                maxSegment=max((x['segment'] for x in obs if isinstance(x.get('segment'),int)),default=None),
                states=dict(collections.Counter(x['poseState'] for x in obs)),
                poseReasons=dict(collections.Counter(x.get('poseReason') for x in obs)),
                applied=r['inputSummary']['applied'],timings=timings,
                stageCounts=dict(collections.Counter(x['stage'] for x in stages)),stageDataIsTailOnly=True,
                clientVersion=r.get('clientVersion'),nativeTimelinePresent='nativeInputs' in r))
    return sorted(result,key=lambda r:r['localTime'])


def render(rows, output, archive_count):
    from PIL import Image,ImageDraw,ImageFont
    footer=max(1037,664+len(rows)*47+32)
    im=Image.new('RGB',(1800,footer+153),'#091321');d=ImageDraw.Draw(im)
    font=lambda n,b=False:ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if b else 'C:/Windows/Fonts/segoeui.ttf',n)
    def text(x,y,s,n=22,color='#edf5ff',bold=False):d.text((x,y),s,font=font(n,bold),fill=color)
    date=datetime.fromisoformat(rows[0]['localTime']).strftime('%d.%m.%Y') if rows else ''
    text(65,35,'SPHERE / РАЗБОР ЖИВЫХ ПРОГОНОВ / '+date,18,'#38d5ee',True)
    text(65,76,'Почему движение прерывалось',44,bold=True)
    span=f"{rows[0]['localTime'][11:16]}–{rows[-1]['localTime'][11:16]}" if rows else 'нет данных'
    text(65,140,f'Сохранены {len(rows)} попыток · {span} · исходный архив: {archive_count} отчёта',23,'#a6b9cd')
    d.rounded_rectangle((65,200,1735,520),18,fill='#102033',outline='#29455e')
    text(90,217,'Максимальные задержки в сохранённой части логов',26,bold=True)
    ceiling=max(850,max((v.get('maximum',0) for r in rows for v in r['timings'].values()),default=0)*1.08)
    for i,(kind,label) in enumerate([('source_gap','Пауза кадров'),('jpeg','Подготовка JPEG'),('http','HTTP-ответ')]):
        value=max((r['timings'].get(kind,{}).get('maximum',0) for r in rows),default=0)
        y=280+i*66;text(95,y,label,22);d.rounded_rectangle((390,y+5,390+value/ceiling*1120,y+30),7,fill='#ffb963')
        text(min(1560,410+value/ceiling*1120),y,f'{value:.1f} мс',20)
    x=390+250/ceiling*1120;d.line((x,268,x,472),fill='#f37c83',width=2);text(x+8,478,'250 мс · предел свежести',18,'#f3a4a8')
    text(95,560,'Наблюдения и причины завершения',28,bold=True)
    for x,label in [(95,'Время'),(270,'Кадры'),(445,'Локализованы'),(730,'Android ACK*'),(1020,'Завершение')]:text(x,615,label,20,'#a6b9cd',True)
    reasons={'walk_manual_stop':'стоп / потеря фокуса прежнего клиента','walk_relocalization_timeout':'восстановление дольше 2 с','walk_relocalization_budget':'лимит потерь позиции','walk_no_route_progress':'продвижение не подтверждено'}
    for i,r in enumerate(rows):
        y=664+i*47
        text(95,y,r['localTime'][11:19],21);text(270,y,str(r['observations']),21)
        text(445,y,str(r['states'].get('localized',0)),21,'#78e3b5' if r['states'].get('localized',0) else '#ffb963')
        text(730,y,str(r['applied']),21);text(1020,y,reasons.get(r['stop'],r['stop']),21,'#ffb963')
    text(65,footer,'* Подтверждены команды стику; это число включает возврат в центр и не измеряет пройденный путь.',21,'#a6b9cd')
    text(65,footer+45,'Новый контур различает ручной стоп, скрытие вкладки и отсутствие продвижения при применённом стике.',22,'#78e3b5')
    im.save(output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',required=True,type=Path)
    p.add_argument('--since',required=True);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();rows=analyze(args.archive,datetime.fromisoformat(args.since).timestamp())
    args.output.mkdir(exist_ok=True,parents=True)
    (args.output/'walk-live-report-analysis.json').write_text(json.dumps(dict(schema='sphere-live-walk-analysis-v1',reports=rows),indent=2),encoding='utf-8')
    with zipfile.ZipFile(args.archive) as z:archive_count=len(z.infolist())
    render(rows,args.output/'walk-live-report-analysis.png',archive_count);print('reports',len(rows))
