# Android codec input: измерения и следующий canary

**Дата:** 1 октября 2026, Asia/Yekaterinburg. **Статус:** native diagnostic принят;
полный capture → encoder → wire → browser путь ещё не принят.

[Текущее состояние](CURRENT-STATE.md) · [Video cadence](VIDEO-CADENCE-CANARY.md) ·
[Данные измерений](../audits/2026-10-01/PH010-CODEC-INPUT-EVIDENCE.json)

## Что изменилось в диагнозе

На PH010 / APK 1.2.38 программный `OMX.google.h264.encoder` ранее давал около
6 pictures/s при Surface input. Это не доказывало, что сам алгоритм AVC слишком
медленный: Surface включает графический producer/consumer и преобразование
пикселей. Отдельный процесс `app_process` сравнил Surface и planar YUV input
без MediaProjection, сети, Sphere transport, браузера и реального экрана.

Одинаковые размеры **960×540**, target **30 FPS**, requested **1.5 Mbit/s**,
движущийся квадрат и полосы. Measurement interval — **1.2 s**, warmup — 150 ms.
Выход дожидается всех измеренных PTS не более 1 s. Codec config не считается
picture; `inflight_at_drain_deadline` во всех пяти окончательных controls — 0.
Это короткий синтетический тест, не длительная оценка качества или стабильности.

| Codec / input | Pictures / 1.2 s | Input FPS | Время от input PTS до output callback |
| --- | ---: | ---: | --- |
| AVC / Surface, requested CBR | 8 | 6.67 | 418–488 ms |
| AVC / Surface, VBR | 8 | 6.67 | 419–495 ms |
| VP8 / Surface, CBR | 8 | 6.67 | 716–783 ms |
| AVC / YUV420 planar, requested CBR | 36 | 30 | 1.29–2.46 ms |
| VP8 / YUV420 planar, CBR | 36 | 30 | 1.41–3.56 ms |

Input FPS здесь — число реально полученных encoded pictures с PTS внутри
measurement interval, делённое на его длительность. Это **не browser draw FPS**
и не callback arrival rate. Surface swap — 136–178 ms в окончательной серии;
planar copy/fill — 0.088–0.256 ms. Planar fixture уже содержит YUV и **не включает
RGBA → YUV conversion настоящего захвата**. Цвета близки к Surface fixture, но
не утверждается pixel-identical equivalence после subsampling/codec conversion.

Runtime capabilities для AVC/VP8/VP9 вернули только Google OMX encoders. AVC:
VBR advertised, CBR not advertised, complexity range `[0,0]`; фактический
configure с requested CBR всё же прошёл. VBR не ускорил Surface path. VP8 не
устранил Surface ограничение; менять wire format на VP8 по этим данным незачем.
На API 28 hardware-acceleration flags API 29 не доступны. Ранее прочитанная AVC
библиотека имеет x86 ELF header; это не доказательство идентичности её source AOSP.

Вывод: **на этом устройстве задержка локализована в графическом input path**,
а не в Python backend или чистом AVC encode синтетического YUV. Конкретный
driver/conversion call пока не изолирован. Это не снимает remote network,
source display FPS limit, реальную conversion cost и browser latency gates.

## Инструмент и условия повторения

Исходник: [MediaCodecProbe.java](../../scripts/pilot/android/MediaCodecProbe.java).
Сборка: [build_codec_probe.py](../../scripts/pilot/build_codec_probe.py), JDK 17+
и установленный Android SDK. APK и Gradle dependencies не меняются.

```powershell
python scripts/pilot/build_codec_probe.py --sdk <sdk-directory> --java-home <jdk-directory> --output <fresh-directory>/probe.zip
```

После проверки SHA256 доставленного, только собственного файла на тестовый Android:

```text
CLASSPATH=/data/local/tmp/<owned-probe>.zip app_process /system/bin com.sphereplatform.audit.MediaCodecProbe inventory
CLASSPATH=/data/local/tmp/<owned-probe>.zip app_process /system/bin com.sphereplatform.audit.MediaCodecProbe bench OMX.google.h264.encoder cbr
CLASSPATH=/data/local/tmp/<owned-probe>.zip app_process /system/bin com.sphereplatform.audit.MediaCodecProbe bench OMX.google.h264.encoder vbr
CLASSPATH=/data/local/tmp/<owned-probe>.zip app_process /system/bin com.sphereplatform.audit.MediaCodecProbe bench-planar OMX.google.h264.encoder
```

Не добавлять host ADB / PC Agent как обязательную зависимость продукта. Для этого
control использован существующий authenticated APK root SHELL. Проверены online,
version 10238 и `not_streaming` перед запуском; сторонние Activity и settings не
менялись. Прямой временный LAN payload server оказался недоступен и был закрыт.
Доставка прошла через одну временную exact diagnostic location существующего
gateway. Nginx configuration проверена до reload, затем исходные байты восстановлены
и выполнен graceful reload. Host и Android payload files удалены; private bootstrap,
OTA catalog и tunnel endpoints не изменялись. Не публиковать диагностический путь
постоянно. Unknown shell timeout требует reconciliation, а не повторного запуска.

Каждый benchmark создаёт и освобождает собственный codec; отдельный callback
thread, bounded collections, finite input/drain. API 28 `app_process` требует
подготовки main Looper даже с explicit callback Handler. Первые controls до этой
поправки завершились JSON error и **не являются FPS measurements**. Ошибка JSON
означает неуспех диагностики даже при нулевом process exit code.

## Исправление, которое следует проверять

**Source candidate 1.2.39 / 10239:** путь реализован под
`SPHERE_STREAM_PLANAR_INPUT=true`, только debug artifact; одновременно включать
GPU bridge нельзя. Default — false, release-shaped Gradle tasks с этим canary
flag отклоняются. Вход ImageReader остаётся RGBA, native geometry сохраняется,
буферы RGBA/I420 переиспользуются; нет Bitmap/Canvas/encoder input Surface.
Google AVC planar capability проверяется до создания VirtualDisplay. Если такой
codec/input недоступен, запуск возвращается к прежнему Surface path до расходования
projection token. После runtime capture failure projection не переиспользуется
автоматически ради смены input path.

Planar timestamps берутся из Image producer, повторные/неположительные не создают
новые pictures. Нет свободного codec input — raw skip без blocking wait;
`encoder_input_drops_total` отличает его от FPS throttle и coded-picture loss.
В API/Prometheus extension optional: старый агент означает unknown, а не zero;
устаревшая gauge удаляется. UI диагностики выводит этот счётчик отдельно. API/UI
runtime должны быть обновлены для отображения нового поля; существующий AVC wire
protocol и decoder менять для самого видеопути не требуется.

До configured artifact build: **43 targeted Android tests**, включая 13 conversion,
6 codec-input ownership и 20 capture lifecycle, пройдены; 20 backend diagnostic/
metric tests, frontend 567 tests и type-check пройдены. Эти tests не исполняют
реальный MediaProjection/OMX и не закрывают FPS/quality acceptance. Полная configured
APK сборка обеих flavors и установка на canary — следующий этап.

1. Canary RGBA ImageReader → переиспользуемый I420 buffer → тот же AVC encoder.
   Native resolution, один real input timestamp на кадр, raw drop при отсутствии
   codec input buffer. Coded pictures не выбрасывать из reference chain.
2. Валидация channel order, row/pixel stride, последней строки без padding,
   BT.601 limited-range conversion, 2×2 chroma, input buffer bounds. Lifecycle:
   stop/restart, stale callback, configure failure, input exhaustion.
3. Измерить **настоящий** RGBA conversion, Android source cadence и wire pictures
   на движущемся экране. Отдельно проверить quality, receive/draw и input-to-visible
   latency, затем remote/reconnect. Synthetic 30 FPS не закрывает эти пункты.
4. Default capture и normal/global OTA сохраняются до acceptance. Canary flag не
   должен попадать в release artifact без отдельного подтверждённого этапа.

## Контракты, лицензия и авторство

[Android MediaCodec](https://developer.android.com/reference/android/media/MediaCodec),
[EncoderCapabilities](https://developer.android.com/reference/android/media/MediaCodecInfo.EncoderCapabilities),
[MediaCodecList](https://developer.android.com/reference/android/media/MediaCodecList).
Проверены 1 октября 2026. Это API contracts; числа выше получены с устройства.
Probe и build helper написаны в Sphere, распространяются под [MIT проекта](../../LICENSE).
Код сторонних codec implementations не копировался, новая runtime dependency не добавлена.
