"""Render real attempt interruptions and separately labelled software checks."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    from PIL import Image,ImageDraw,ImageFont
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('summary','simulation','layout','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise ValueError('new_output_required')
    data=json.loads(args.summary.read_bytes());sim=json.loads(args.simulation.read_bytes());layout=json.loads(args.layout.read_bytes())
    runs=[r for r in data if r['count']>0];args.output.mkdir(parents=True)
    image=Image.new('RGB',(1800,1160),'#081321');draw=ImageDraw.Draw(image)
    def text(x,y,s,size=21,color='#a5b9cd',bold=False):
        f=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf' if bold else 'C:/Windows/Fonts/segoeui.ttf',size)
        draw.text((x,y),str(s),font=f,fill=color)
    def panel(x,y,w,h):draw.rounded_rectangle((x,y,x+w,y+h),radius=17,fill='#101f30',outline='#29435b',width=2)
    text(52,30,'SPHERE  /  KAKASKA228  /  WALK CONTINUITY',19,'#59dbc6',True)
    text(52,68,'Маршрут узнавался. Прерывался контур управления.',38,'#edf6ff',True)
    text(52,125,'Реальные отчёты 31 октября, 01:10–01:14 · walk_live_v7 · новый игровой прогон v8 не выполнен',22)
    end=max((r['progress'][0]for r in runs if r['progress']),default=0)
    motion=sum((r['motionSeconds'][0]for r in runs if r['motionSeconds']),0)
    wall=sum(r['seconds']for r in runs)
    cards=[('ПЯТЬ ЗАПУСКОВ',f'{end*100:.1f}%','Последняя узнанная точка на дуге карты'),
           ('ТЕЛЕМЕТРИЯ ДВИЖЕНИЯ',f'{motion:.1f} / {wall:.1f} с','Применённый стик / время выборок'),
           ('ОСТАНОВКИ ПО ЛИМИТУ ПОИСКА','3','Суммарные 6 секунд ожидания в v7')]
    for i,(label,value,note)in enumerate(cards):
        x=52+i*574;panel(x,178,552,135);text(x+20,194,label,18,'#85a4c1',True);text(x+20,220,value,36,'#f1f8ff',True);text(x+20,275,note,18)
    panel(52,337,1696,391);text(76,356,'Участки продвижения в отдельных запусках',27,'#edf6ff',True)
    text(76,400,'Каждая строка — отдельный запуск. Разрывы не склеены в «успешный полный проход».',20)
    x0,w=525,1145
    for frac in (0,.25,.5,.75,1):
        x=x0+w*frac;draw.line((x,448,x,686),fill='#284159');text(x-12,687,f'{frac*100:g}%',17)
    colors=['#46cbdc','#7da4ff','#b995ff','#66dfbd','#ffbe76']
    for i,r in enumerate(runs):
        y=455+i*46;raw=json.loads((args.summary.parent/(r['id']+'.json')).read_bytes())
        values=[v['progress']for v in raw['observations']if v['progress']is not None]
        if not values:continue
        start,last=values[0],values[-1]
        reason={'walk_recovery_time_budget':'лимит ожидания','contact_video_stale':'нет нового кадра','walk_visibility_pause':'скрытие вкладки'}.get(r['stop'],r['stop'])
        text(76,y-10,f"{i+1:02d}   {r['seconds']:.1f} с · {reason}",19)
        a=x0+w*start;b=x0+w*last;draw.line((a,y+4,b,y+4),fill=colors[i],width=7)
        draw.ellipse((b-5,y-1,b+5,y+9),fill=colors[i]);text(min(1678,b+12),y-11,f'{last*100:.1f}',17,colors[i],True)
    panel(52,751,828,240);panel(904,751,844,240)
    text(76,771,'Исправлено в v8',25,'#edf6ff',True)
    for i,s in enumerate(['Короткие задержки не копятся в вечный лимит 6 с.','Пауза кадров до 3 с сохраняет нейтральный сеанс.','Умеренный поворот и перенос пальца — на ходу.','Знак измеренной камеры сохранён после паузы.']):text(76,819+i*37,s,20)
    text(928,771,'Проверено вне игры',25,'#edf6ff',True)
    text(928,819,f"Симуляция камеры: {sum(bool(c['passed'])for c in sim['cases'])} / {len(sim['cases'])} сценариев",22,'#59dbc6',True)
    text(928,858,'Задержки, две оси, touch slop, пропадание кадров.',20)
    text(928,899,f"Перестроение статуса: сдвиг {layout['maximumShiftPx']:g} px",22,'#59dbc6',True)
    text(928,939,'Chromium · реальные компоненты и карта · без ввода.',20)
    text(52,1020,'174 камеры — опорная карта; свежие кадры оцениваются между ними. Контакт стика удерживается.',23,'#edf6ff',True)
    text(52,1060,'Скорость персонажа, метрическая точность и полный проход v8 ещё не измерены. Объезд препятствий не добавлялся.',20)
    text(52,1104,'Пунктир — прошлое измерение, не предсказанная поза и не разрешение продолжать вслепую.',20,'#ffcc8d')
    image.save(args.output/'continuity-evidence.png')
    receipt=dict(schema='sphere-walk-continuity-board-v1',physicalActions=0,liveCompletionVerified=False,
        runs=len(runs),latestMapProgress=end,motionSeconds=motion,retainedRunSeconds=wall,
        hashes={name:hashlib.sha256(getattr(args,name).read_bytes()).hexdigest()for name in ['summary','simulation','layout']})
    (args.output/'board.json').write_text(json.dumps(receipt,indent=2),'utf-8');print(json.dumps(receipt))


if __name__=='__main__':main()
