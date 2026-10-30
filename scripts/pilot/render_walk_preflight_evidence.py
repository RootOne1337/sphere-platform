"""Measured camera simulation and video replay board; no invented road geometry."""
import argparse
import json
import math
from pathlib import Path


def render(before, after, replay, output):
    from PIL import Image, ImageDraw, ImageFont
    before, after, replay = [json.loads(Path(p).read_text('utf-8')) for p in (before, after, replay)]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    regular = 'C:/Windows/Fonts/segoeui.ttf'
    bold = 'C:/Windows/Fonts/segoeuib.ttf'
    font = lambda size, heavy=False: ImageFont.truetype(bold if heavy else regular, size)
    bg, panel, muted, white = '#091321', '#102033', '#a6b9cd', '#edf5ff'
    cyan, amber, green = '#38d5ee', '#ffb963', '#78e3b5'
    image = Image.new('RGB', (1800, 1190), bg)
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=22, fill=white, heavy=False):
        draw.text((x, y), value, font=font(size, heavy), fill=fill)

    text(65, 35, 'SPHERE / ПРОВЕРКА КОНТУРА / 30.10.2026', 18, cyan, True)
    text(65, 75, 'Сначала проверяем отказы на стенде', 43, heavy=True)
    text(65, 135, 'Код камеры и Android-контактов настоящий. Реакция игры в этом тесте — модель.', 24, muted)
    passed_before = sum(c['terminal'] is None and c['alignedAtMs'] is not None for c in before['cases'])
    metrics = [
        ('БАЗОВЫЕ 13 СЦЕНАРИЕВ', f'{passed_before} → 13', 'Успешное выравнивание камеры'),
        ('РАСШИРЕННЫЙ СТЕНД', f"{sum(c['passed'] for c in after['cases'])} / {len(after['cases'])}", 'Включая два ожидаемых отказа'),
        ('ЖИВОЙ ПРОХОД В ИГРЕ', 'не подтверждён', 'Стенд не доказывает прохождение A → B'),
    ]
    for i, (label, value, detail) in enumerate(metrics):
        x = 65+i*565
        draw.rounded_rectangle((x, 200, x+540, 345), 18, fill=panel, outline='#29455e')
        text(x+23, 217, label, 17, muted, True)
        text(x+23, 250, value, 34, green if i<2 else amber, True)
        text(x+23, 302, detail, 18, muted)

    draw.rounded_rectangle((65, 380, 1735, 825), 18, fill=panel, outline='#29455e')
    text(92, 400, 'Угловая ошибка камеры · один и тот же сценарий до и после', 26, heavy=True)
    text(92, 441, 'Задержка 60 мс · порог срабатывания жеста 16 px · чувствительность X=12, Y=−8', 20, muted)
    find = lambda dataset: next(c for c in dataset['cases'] if c['config']['gainX']==12 and c['config']['visualMs']==60 and c['config']['slopPx']==16)
    left, top, width, height = 150, 510, 1470, 235
    for degree in (0, 30, 60, 90):
        y = top+height*(1-degree/90)
        draw.line((left, y, left+width, y), fill='#274056')
        text(97, y-12, f'{degree}°', 18, muted)
    for seconds in range(7):
        x = left+width*seconds/6
        draw.line((x, top, x, top+height), fill='#21374d')
        text(x-10, top+height+12, str(seconds), 18, muted)
    for dataset, color in ((before, amber), (after, cyan)):
        points = [(left+width*r['ms']/6000, top+height*(1-min(90,math.degrees(r['physicalError']))/90)) for r in find(dataset)['rows'] if r['ms']<=6000]
        draw.line(points, fill=color, width=4)
        x,y=points[-1];draw.ellipse((x-6,y-6,x+6,y+6),fill=color)
    text(1200, 468, '■ прежний код', 18, amber)
    text(1420, 468, '■ исправленный', 18, cyan)
    text(1550, 785, 'секунды', 18, muted)

    text(65, 860, 'Вся запись → HTTP-локализатор → планировщик', 30, heavy=True)
    text(65, 913, f"{replay['observations']} отложенных кадров · {replay['lastSeconds']:.2f} с · {replay['counts'].get('localized',0)} локализованы", 25, cyan)
    text(65, 957, f"Ответ p50 / p95: {replay['replyMs']['p50']:.1f} / {replay['replyMs']['p95']:.1f} мс · private memory: {replay['peakSampledPrivateBytes']/1024**2:.1f} МиБ", 23)
    text(65, 1001, 'Видео не реагирует на команды. Остановки планировщика разобраны отдельно в отчёте.', 23, amber)
    text(65, 1054, 'Метры, проходимость дороги и точность прохождения в живой игре этим не измерены.', 22, muted)
    text(65, 1097, 'Никаких касаний Android · исходное видео и геометрия сохранены', 22, green)
    path = output/'walk-preflight-evidence.png'
    image.save(path)
    return path


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('before','after','replay','output'):parser.add_argument('--'+name,required=True,type=Path)
    args=parser.parse_args();print(render(args.before,args.after,args.replay,args.output))
