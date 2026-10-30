"""Comparison diagram and measured playback progress, not a claimed game run."""
import argparse
import json
from pathlib import Path


def render(before, after, output):
    from PIL import Image, ImageDraw, ImageFont
    before,after=[json.loads(Path(p).read_text('utf-8')) for p in (before,after)]
    font=lambda size,bold=False:ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',size)
    im=Image.new('RGB',(1800,1190),'#091321');d=ImageDraw.Draw(im)
    white,muted,cyan,green,amber='#edf5ff','#a6b9cd','#38d5ee','#78e3b5','#ffb963'
    def text(x,y,value,size=22,color=white,bold=False):d.text((x,y),value,font=font(size,bold),fill=color)
    text(65,35,'SPHERE / ПОВТОРНЫЕ ПРОХОДЫ / 30.10.2026',18,cyan,True)
    text(65,75,'Второй проход проверяет первый',44,bold=True)
    text(65,138,'Одна опорная карта · новое видео сверяется с ней · исходная геометрия сохраняется',23,muted)
    for i,(title,lines,color) in enumerate([
        ('01  Опорная запись',['Видео → камеры → 3D-ориентиры','Задаёт последовательность маршрута'],cyan),
        ('02  Независимый проход',['Другая скорость и небольшой сдвиг','Позы определяются по первой карте'],green),
        ('03  Проверка расхождений',['Узнавание, ракурс, прогресс, задержки','Добавление в карту — отдельный этап'],amber)]):
        x=65+i*565;d.rounded_rectangle((x,205,x+540,365),18,fill='#102033',outline='#29455e')
        text(x+22,225,title,26,color,True)
        for j,line in enumerate(lines):text(x+22,280+j*31,line,20,muted)
    d.rounded_rectangle((65,400,1735,830),18,fill='#102033',outline='#29455e')
    text(90,421,'Планировщик на сохранённой записи · прогресс по пути камеры',26,bold=True)
    text(90,464,'Это проверка на видео: команды не меняют изображение и не двигают персонажа.',20,muted)
    left,top,width,height=155,530,1460,220
    for percent in (0,25,50,75,100):
        y=top+height*(1-percent/100);d.line((left,y,left+width,y),fill='#294055');text(95,y-13,f'{percent}%',18,muted)
    for seconds in (0,10,20,30,40,50):
        x=left+width*seconds/51;d.line((x,top,x,top+height),fill='#21374d');text(x-9,top+height+13,str(seconds),18,muted)
    for source,color in ((before,amber),(after,green)):
        points=[(left+width*r['seconds']/51,top+height*(1-r['progress'])) for r in source['samples'] if r['progress'] is not None]
        d.line(points,fill=color,width=4)
        x,y=points[-1];d.ellipse((x-5,y-5,x+5,y+5),fill=color)
    text(1150,490,'■ прежний прогон',18,amber);text(1435,490,'■ после исправлений',18,green)
    text(1490,790,'секунды записи',18,muted)
    end=next((r for r in after['samples'] if r['phase']=='arrived'),None)
    text(65,868,'ПОСЛЕДНИЙ ПРОГОН НА ВИДЕО',18,cyan,True)
    text(65,904,f"{after['counts'].get('localized',0)} / {after['observations']} кадров локализованы · просроченных запросов: {after['expiredQueries']}",28,bold=True)
    text(65,953,f"Подтверждение конца плана: {end['seconds']:.3f} с" if end else 'Конец плана пока не подтверждён',24,green if end else amber)
    text(65,996,f"JPEG + HTTP, p50 / p95: {after['queryAgeMs']['p50']:.1f} / {after['queryAgeMs']['p95']:.1f} мс",23)
    text(65,1049,'Независимый ручной проход того же маршрута ещё нужен для проверки устойчивости ракурса.',22,muted)
    text(65,1092,'Завершение плана на видео не доказывает прохождение маршрута в живой игре.',22,amber)
    output=Path(output)
    if output.exists():raise ValueError('repeat_evidence_exists')
    im.save(output);return output


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','output'):p.add_argument('--'+name,required=True,type=Path)
    args=p.parse_args();print(render(args.before,args.after,args.output))
