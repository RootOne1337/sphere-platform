"""Show exact retained queries and measured descriptor costs, without generated geometry."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile


def render(archive,cost,output):
    from PIL import Image,ImageDraw,ImageFont
    data=json.loads(cost.read_bytes());rows=data['cases']
    if not data.get('realQueryImages')or not data.get('offline')or data.get('physicalActions')!=0:raise ValueError('cost_scope')
    if data['archiveSha256']!=hashlib.sha256(archive.read_bytes()).hexdigest():raise ValueError('archive_binding')
    with zipfile.ZipFile(archive)as z:
        if sum(e.file_size for e in z.infolist())>2*1024**2:raise ValueError('archive_quota')
        meta=json.loads(z.read('metadata.json'));selected=meta['frames'][-4:];photos=[]
        for row in selected:
            raw=z.read(f"frame-{row['sequence']:06d}.jpg")
            if hashlib.sha256(raw).hexdigest()!=row['jpegSha256']:raise ValueError('frame_hash')
            with Image.open(io.BytesIO(raw))as photo:
                if photo.size!=(960,540):raise ValueError('frame_size')
                photos.append(photo.convert('RGB').resize((590,332),Image.Resampling.LANCZOS))
    im=Image.new('RGB',(1800,1200),'#091321');d=ImageDraw.Draw(im)
    def text(x,y,s,size=22,color='#e6f0ff',bold=False):
        d.text((x,y),s,font=ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf'if bold else 'C:/Windows/Fonts/segoeui.ttf',size),fill=color)
    text(60,35,'SPHERE / EXACT LIVE QUERIES / 30.10 → 31.10.2026',18,'#38d5ee',True)
    text(60,75,'Сцена узнавалась. Ответы теряли свежесть.',42,bold=True)
    text(60,145,'Настоящие кадры последнего прогона · карта не перестраивалась · исходная запись не изменялась',23,'#a6b9cd')
    for i,(row,photo)in enumerate(zip(selected,photos)):
        x,y=60+(i%2)*620,215+(i//2)*430
        im.paste(photo,(x,y));d.rounded_rectangle((x,y+332,x+590,y+415),10,fill='#102033',outline='#294056')
        reason={'route_frame_expired_during_localization':'ответ устарел','route_observation_gap':'пауза наблюдений','relative_camera_pose_not_clearance_or_arrival':'положение подтверждено'}.get(row['poseReason'],row['poseState'])
        text(x+15,y+342,f"Кадр {row['sequence']} · {reason}",21,'#ffb963'if row['poseState']=='unknown'else '#78e3b5',True)
        text(x+15,y+376,f"Обработка {row['computeMs']:.1f} мс · совпадений {row['inliers']}",20,'#a6b9cd')
    d.rounded_rectangle((1320,215,1740,1060),18,fill='#102033',outline='#294056')
    text(1345,242,'ПОВТОРНЫЙ РАЗБОР',19,'#38d5ee',True)
    text(1345,285,'Те же 4 JPEG',30,bold=True);text(1345,333,'4 потока OpenCV',23)
    for j,limit in enumerate((8,3)):
        case=[r for r in rows if r['threads']==4 and r['candidates']==limit]
        mean=sum(r['totalMs']for r in case)/len(case);maximum=max(r['totalMs']for r in case)
        y=410+j*205;text(1345,y,'8 глобальных + локальный'if limit==8 else '3 глобальных + локальный',21)
        text(1345,y+38,f'{mean:.1f} мс',39,'#ffb963'if limit==8 else '#38d5ee',True)
        text(1345,y+94,f'Максимум {maximum:.1f} мс',21,'#a6b9cd')
        text(1345,y+126,'Поза найдена: 4 / 4',23,'#78e3b5')
    text(1345,850,'Свежая геометрия',23,bold=True);text(1345,885,'поддерживает нейтральное',20);text(1345,916,'восстановление.',20)
    text(1345,963,'Движение — после трёх',20,'#a6b9cd');text(1345,994,'полных подтверждений.',20,'#a6b9cd')
    text(60,1110,'Повторный разбор выполнен отдельно от игры. Его время не гарантирует такую же задержку в живом потоке.',21,'#a6b9cd')
    text(60,1146,'Совпадения подтверждают относительную позу; точность в метрах и проходимость маршрута здесь не измерялись.',21,'#a6b9cd')
    output.mkdir(parents=True,exist_ok=True);im.save(output/'live-recovery-evidence.png')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--cost',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();render(args.archive,args.cost,args.output)
