"""Compare matched scripted camera plants, never a claim about real-game accuracy."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def compare(before,after,output):
    from PIL import Image,ImageDraw,ImageFont
    def load(path):
        if path.stat().st_size>4*1024**2:raise ValueError('simulation_quota')
        data=json.loads(path.read_bytes())
        if not data.get('simulatedPlant') or data.get('realGame') or data.get('actualLocalization'):
            raise ValueError('simulation_scope')
        case=next(c for c in data['cases'] if c['config'].get('movingReference'))
        if len(case['rows'])>2500:raise ValueError('simulation_row_quota')
        return data,case
    a,old=load(before);b,new=load(after)
    if old['config']!=new['config']:raise ValueError('simulation_configuration_changed')
    for source in ('teachingContacts.ts','walkCamera.ts'):
        if a['productionSources'][source]!=b['productionSources'][source]:raise ValueError('plant_input_runtime_changed')
    image=Image.new('RGB',(1800,1000),'#091321');draw=ImageDraw.Draw(image)
    def text(x,y,value,size=22,color='#dfeafa',bold=False):
        font=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',size)
        draw.text((x,y),value,font=font,fill=color)
    text(65,40,'SPHERE / CONTINUOUS CAMERA / SCRIPTED CLOSED LOOP',18,'#38d5ee',True)
    text(65,85,'Поворот без повторной активации пальца',42,bold=True)
    text(65,153,'Моделирование · 50 секунд · задержка изображения 100 мс · реальные игровые кадры не использовались',22,'#a6b9cd')
    text(85,225,'Угловая ошибка после начальной калибровки, градусы',24,bold=True)
    x0,y0,width,height=120,290,1070,440
    for degree in range(0,21,5):
        y=y0+height-degree/20*height;draw.line((x0,y,x0+width,y),fill='#294056');text(x0-42,y-13,str(degree),19,'#a6b9cd')
    for sec in range(5,51,5):
        x=x0+(sec-5)/45*width;draw.line((x,y0,x,y0+height),fill='#1a2e44');text(x-10,y0+height+14,str(sec),19,'#a6b9cd')
    for case,color,label in [(old,'#ffb963','Прежний контур'),(new,'#38d5ee','Новый контур')]:
        rows=[row for row in case['rows'] if 5000<row['ms']<=50000]
        points=[(x0+(r['ms']/1000-5)/45*width,y0+height-min(20,math.degrees(r['physicalError']))/20*height) for r in rows]
        draw.line(points,fill=color,width=3)
    draw.line((140,806,175,806),fill='#ffb963',width=4);text(188,790,'Прежний контур',22,'#ffb963')
    draw.line((500,806,535,806),fill='#38d5ee',width=4);text(548,790,'Новый контур',22,'#38d5ee')
    for i,(case,color,label) in enumerate([(old,'#ffb963','Раньше'),(new,'#38d5ee','Теперь')]):
        x,y=1280,285+i*215;draw.rounded_rectangle((x,y,1735,y+185),18,fill='#102033',outline='#294056')
        text(x+25,y+18,label,22,color,True)
        noun='касание' if case['cameraDowns']==1 else 'касаний'
        text(x+25,y+55,f"{case['cameraDowns']} {noun} DOWN",32,bold=True)
        text(x+25,y+113,f"Средняя ошибка {math.degrees(case['trackingError']['mean']):.2f}°",22)
        text(x+25,y+145,'Остановка: '+('нет' if case['terminal'] is None else case['terminal']),19,'#a6b9cd')
    text(65,890,'Сравнивается тот же сценарий и тот же протокол касаний. Ошибка — ориентация камеры в симуляторе.',21,'#a6b9cd')
    text(65,930,'Это не измерение отклонения персонажа в метрах и не подтверждение прохождения маршрута в игре.',21,'#a6b9cd')
    output.mkdir(parents=True,exist_ok=True);image.save(output/'camera-continuity-comparison.png')
    result=dict(schema='sphere-camera-continuity-comparison-v1',simulatedPlant=True,realGame=False,actualLocalization=False,
        inputSha256=[hashlib.sha256(p.read_bytes()).hexdigest()for p in (before,after)],config=old['config'],
        cases=[dict(label=label,cameraDowns=c['cameraDowns'],moves=c['moves'],terminal=c['terminal'],trackingError=c['trackingError'])for label,c in [('before',old),('after',new)]])
    (output/'camera-continuity-comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True);parser.add_argument('--after',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();compare(args.before,args.after,args.output)
