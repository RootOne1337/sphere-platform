# Worker0.8.0: обучающая запись и последовательная память маршрута

Дата:24 октября2026 UTC+5; испытания23 октября UTC. База исходников `1f2baa19`.
[Машинная квитанция](MOTOR-TEACHING080.json), SHA-256 normalized LF:
`0cf7f59673170333c430777e4fb59ba87e961a811a95b58a22989778f28a3650`.

**Дополнение после исходной квитанции:** [реальные native-жесты](MOTOR-TEACHING080-NATIVE.json),
SHA-256 normalized LF `bcef9ae39eecf19b1bf0ca268ae26e004ddfc0f746c33d6085252c5fc1da737b`.
На том же коде подтверждены два жеста PH011/14 APPLIED, в том числе непрерывное
удержание3016мс. Игра явно отключена за бездействие; navigation этим не проверена.
Инфраструктура допущена к **контролируемому опыту качественной записи** после
восстановления игрового мира. Настоящий1080p60 ещё предстоит измерить.

Реализован первый исполнимый этап teach-and-repeat: явная запись исходного видео,
журнал собственного ручного ввода, проверяемый dataset, компиляция ограниченной
последовательности видов и оценка её узнаваемости. Это подготовка контролируемой
демонстрации, ещё не автономный маршрут с объездом и подтверждённым прибытием.
Product acceptance остаётся9/41/50. Установленные APK88/API/UI и VPN не менялись;
новых GitHub jobs, моделей и provider peers нет. Основной веб не получил новый модуль:
панель пока запускается отдельно из локального SDK.

## Что реализовано

| Компонент | Поведение и граница |
| --- | --- |
| `teach_capture.py` | Depacketized H.264 AnnexB до decode/host rendering. Сохраняет исходные access units без перекодирования; ждёт SPS/PPS+IDR. |
| `receiver.py`/`session.py` | Явный opt-in sink; capture epoch и геометрия закреплены. По умолчанию записи нет. Потеря целостности/PLI после начала прекращает dataset. |
| `teach_operator.py/.html` | Временный localhost-интерфейс одного оператора/одного пальца; down→MOVE→up либо подтверждённое закрытие. Не захватывает клавиатуру LDPlayer. |
| `teach.py` | CLI `record`, `operator`, `inspect`, `compile`, `quality`. `record` не открывает native control; `operator` требует отдельный флаг. |
| `route_memory.py` | Версионированные2–64 checkpoints с feature-файлами, профилем, source ticks и digest исходного manifest. Это упорядоченная цепочка, не дорожный граф. |
| `RouteProgress` | Только наблюдение: первый checkpoint, три последовательных подтверждения, поиск в соседних видах, привязка к epoch/episode/goal. Последний вид означает `end_view`, не arrival. |
| `route_quality.py` | Offline проверка отложенных кадров не чаще5Гц с явным downscale/JPEG; неоднозначность и unknown учитываются отдельно. Никакого Android input. |

H.264 записывается с фактической частотой источника.5Гц относится к наблюдениям
политики/базовому предпросмотру, а не к частоте master recording. Предпросмотр можно
явно выбрать5/10/15/20Гц; он ограничен960×540 и не меняет качество master.
Удержание пальца сохраняется между MOVE и не превращается в повторные tap.
Журнал — данные жеста и receipts, не сотни нод сценария.

## Формат и clocks

Новая неперезаписываемая папка содержит только:

- `video.h264`: encoded stream без аудио;
- `frames.jsonl`: sequence, byte offset/size, relative RTP ticks90kHz,
  worker receive time, IDR flag;
- `inputs.jsonl`: только собственные отправленные pointer changes и native
  APPLIED/CLOSED. Owner/token/text не записываются;
- `manifest.json`: device/episode/profile/capture UUID, geometry, clocks,
  количество событий/кадров и SHA-256 артефактов;
- `COMPLETE`: digest manifest, записывается последним после fsync/закрытия writer
  и проверки terminal input state. Без него импорт отклоняется.

RTP media time, worker `perf_counter` и Android `uptime_ms` **раздельны**.
Соответствие source capture time↔native APPLIED не измерено. Поэтому manifest
обязательно содержит `source_capture_clock_mapping_known=false`,
`quality_qualified=false`. Совпадение единиц времени не делает clocks синхронными.
APPLIED доказывает инъекцию, не движение персонажа. Device boot identity/точный
capture→action mapping остаются следующей частью Android metadata contract.

Журнал охватывает собственный input actor. Действия другого зрителя, LDPlayer
keymapper или физической клавиатуры он автоматически не видит. Input ownership
не подменяется статусом видеопотока; нужны native READY **и** текущая manual
availability. Для машины с газом/рулём/камерой одновременно нужен отдельный
multitouch/gamepad adapter; этот этап реализует один палец для пешего прохода.

## Ограничения и остановка

Recorder: максимум300с,2GiB,36000 frames,80000 journal events; defaults120с,
512MiB,18000 frames,40000 events. CLI monitor≤285с оставляет15с для source pre-roll
внутри общего300-секундного media cap. Queue≤32 items/8MiB, access unit≤2MiB.
Writer один; переполнение даёт failure без тихого удаления обучающих кадров.
`finish` ждёт writer до3с; неизвестный retirement не получает COMPLETE.

Нет автоматической перезаписи, удаления, фоновой записи или бесконечного retry.
Оптические кадры не коммитятся в репозиторий. Одноразовые private записи этого
испытания остаются для диагностики; общий TTL/storage lifecycle ещё не реализован.

Manual console: loopback127.0.0.1 с ephemeral port, точные Host/Origin,
случайная HttpOnly/SameSite cookie, CSP; Sphere JWT остаётся в Python. Один
оператор без reconnect/replay. Queue8 сохраняет edges и объединяет только MOVE;
одновременно один pending native command. Command age≤200мс, heartbeat≤350мс.
При удержании receiver age видеокадра>250мс закрывает ввод даже при живом UI.
Blur/скрытие окна/Stop/потеря канала завершают демонстрацию. По close требуется
native release confirmation; отправка stop сама по себе не считается освобождением.

Route importer не исполняет сохранённый ввод. Строгие schemas, byte/hash/count/
PTS checks, fixed filenames, UUID и отсутствие symlink/лишних файлов ограничивают
импорт. Старые записанные pixels используются только в явном offline clock domain.
Live `RouteProgress` получает fresh `PolicyFrame`; не верифицированная scene,
неоднозначность, gap>500мс или потеря вида дают unknown. Смена цели/episode/epoch
и disconnect инвалидируют оценку. Unknown не разрешает движение.

## Проверки и реальные результаты

Финальный набор: **295 motor tests,80,668с,0 failures/errors; Ruff passed**.
Покрыты точные encoded bytes/RTP wrap, незавершённый input, перегрузка writer,
невалидный импорт, corruption, route order/ambiguity/episode/goal, stationary
rejection, real H.264 decode/resize, localhost Origin/cookie, native admission,
Stop, потеря heartbeat и видео при удержании. Промежуточный неуспешный294-test run
сохранён: исправлены порядок Stop/socket close и ожидание собственного task до
закрытия файлов теста. Финальный набор не исключал отказной сценарий.

| Испытание | Наблюдение | Что этим не принято |
| --- | --- | --- |
| PH011 read-only10с |276/276 access units декодированы,960×540,27,464Гц; max receive gap367,097мс |250мс SLA во всех окнах; gameplay/input |
| PH011 финальный read-only5с |137/137 декодированы,27,178Гц; max gap93,791мс; writer/process вышли |Capture→AI/native latency, длительный soak |
| Настоящий CLI `record`5с |136 frames,26,791Гц,max gap181,982мс |Качество route/arrival |
| PH011 native idle |143 frames; READY/manual и CLOSED подтверждены; pointer actions0 |Ручной обучающий жест на Android |
| PH011 browser drag, позднее дополнение |1259/1259 decoded;7/7 APPLIED,1 gesture; COMPLETE/CLOSED |Вход в игру, маршрут/arrival |
| PH011 медленный native probe, позднее дополнение |137/137 decoded;7/7 APPLIED,один3016-мс gesture; COMPLETE/CLOSED |Человеческий маршрут/высокое разрешение |
| Браузер на **fake Android** |1059 frames/35,267 media seconds;30Гц;2/2 fake APPLIED,Stop/CLOSED; clean exit |Физический Android/игровой маршрут |
| Синтетический1080p60 |120/120 encoded frames записаны и offline декодированы |Реальный Android1080p60/source encoder |

Пути real PH011 были nominated UDP host/prflx по private addresses; LAN locality
не доказана этим признаком. Receiver gap — время приёма, не возраст source frame.
В исходной квитанции до native-дополнения физических pointer actions на Android0;
после неё проведены два конечных жеста/14 изменений, без запуска ИИ.
Ранние failures quota/browser heartbeat оставлены в квитанции. Один хороший
короткий повтор не отменяет gap367мс и старый unresolved observer gap1,02с.

Дополнительно найден Python scan до2MiB H.264 на RTP callback: один старый sample
289,076мс. Встроенный `bytes.find` снизил максимум20 синтетических измерений до
0,4524мс (mean0,3543мс). Это устранение CPU stall parser, не end-to-end benchmark.
После изменения повторены295 tests/Ruff и свежая PH011 запись.

## Как воспроизвести

Существующее изолированное motor runtime, optional vision dependencies и текущий
Sphere access token в окружении. Не вставлять token в argv/URL/документы.
Родительские каталоги должны существовать; target directories/output должны
отсутствовать. `DEVICE_UUID`, episode/profile/world UUID выбираются явно.

```powershell
python -m motor_worker.teach record --base-url http://127.0.0.1:3015 --device DEVICE_UUID --episode EPISODE_UUID --profile-revision PROFILE_UUID --seconds 20 --directory C:/captures/route01-video
python -m motor_worker.teach operator --allow-native-input --preview-hz 15 --base-url http://127.0.0.1:3015 --device DEVICE_UUID --episode EPISODE_UUID --profile-revision PROFILE_UUID --seconds 60 --directory C:/captures/route01-teach
python -m motor_worker.teach inspect --directory C:/captures/route01-teach
python -m motor_worker.teach compile --directory C:/captures/route01-teach --output C:/routes/route01 --view-profile examples/motor-route-view-profile.json --world-revision WORLD_UUID --mode pedestrian
python -m motor_worker.teach quality --directory C:/captures/route01-teach --route C:/routes/route01 --render-scale 0.5 --jpeg-quality 75 --output C:/reports/route01-quality.json
```

`operator` печатает короткоживущий локальный URL; при его открытии подготовленный
человек ведёт демонстрацию. `record` — только видео. Настоящий runtime profile
надо откалибровать по geometry/ROI/HUD/avatar; example не квалифицирован для игры.
Aspect ratio source/target должен совпасть. Несколько одинаковых stationary views
не становятся маршрутом: compilation требует≥2 различных обучаемых видов.
Если больше64 checkpoints — демонстрацию надо разделить, а не снять лимит.

`quality` исключает сами reference frames. Если проверяется та же демонстрация,
результат явно помечен `same_demonstration=true`: это не независимый повтор.
Simulated downscale/JPEG не эквивалентен реальному50% game renderer, другому времени
суток, новому spawn, камере или другим игрокам. Для этого нужна отдельная запись.
Resource guard RAM/Windows commit/disk сохранён. Модель для recorder не нужна.

При readback существующего `/api/v1/streaming/{device_id}/quality` после закрытия
PH011 вернул `detail`, `max_fps=60`, `max_bitrate_bps=24000000`, `active=null`.
Настройки не менялись. Это сохранённый ceiling, не доказательство реально снятых
60FPS; после смены разрешения надо проверить active geometry/encoder и новый файл.

## Следующий допуск к качественному обучающему проходу

Transport/journal gate уже проверен native-дополнением: browser drag и отдельное
медленное удержание не содержат повторных DOWN. Для3-с probe worker submission
times0/527,635/1016,049/1509,005/2000,739/2517,567/3018,365мс, Android APPLIED
relative uptime0/526/1013/1507/1998/2516/3016мс. Это отдельные относительные clocks,
не source capture→input mapping. Все1396 frames двух записей декодированы.
Игровой эффект и два поворота ещё не проверены: свежий экран содержит disconnect
за бездействие. Следующие шаги относятся к содержательной демонстрации.

1. Свежий gameplay preflight PH011: после AFK/disconnect закрыть/открыть игру,
   ≥20с между server attempts, подтвердить мир по экрану/XPath. Для GPS-профиля
   заново открыть карту, выбрать точку, «Отслеживать», закрыть и проверить маршрут.
2. В игровом мире проверить короткий **человеческий** проход через console и2
   поворота: игровой эффект/камера, source video, own down/MOVE/up/APPLIED,
   release/COMPLETE, отсутствие другого владельца. Native transport/journal gate
   уже пройден; это ещё не калибровка навыка ходьбы/объезда.
3. Можно подготовить только teaching emulator/game для контролируемой записи:
   native1080p,100% game rendering, сначала30 уникальных FPS; сравнить60FPS для
   motion/corners. Проверить source codec/fps/битрейт, loss/gaps и input receipt,
   не только цифры настроек.120FPS не требуется для первого опыта.
4. Записать короткий маршрут с2 поворотами. На независимом повторе вернуть реальные
   рабочие540p/50% rendering; измерить localization coverage, ошибки вида,
   последовательность/срывы, uncertainty и нагрузку. Не отдавать эту настройку
   глобально всем эмуляторам. При плохой узнаваемости повысить именно нужный ROI/
   rendering profile или добавить anchors, а не считать upscale восстановлением.
5. Лишь затем подключать малоскоростной path follower и obstacle supervisor,
   проверять останов/объезд/возврат/arrival минимум10 независимых повторов. Overlay
   для NitroGen/P2P остаётся отдельным opposite-goal экспериментом, не готовым
   интерфейсом цели. Fleet20/50 устройств и150–250мс полный latency budget открыты.

После native-дополнения инфраструктура готова к первой контролируемой качественной
записи: пользователь может выставить1080p60 для опыта; измерение покажет, получены
ли реальные60 уникальных source FPS или достаточно30. Полноценный scan/controller
и автоматическое движение в этом релизе не объявляются готовыми.

## Основания метода

После повторной сверки [scrcpy recording](https://raw.githubusercontent.com/Genymobile/scrcpy/master/doc/recording.md)
выбран исходный encoded stream: запись окна на ПК добавляет зависимость от host
display timing. Sphere пока сохраняет RTP timeline отдельно от Android uptime,
поэтому не наследует автоматически clock guarantees scrcpy.

[QVPR teach-repeat](https://github.com/QVPR/teach-repeat) демонстрирует visual
teach-and-repeat с monocular camera **и wheel odometry**. Это подтверждает
методологию, но одометрия в игре не появляется из видео автоматически.
[Nav2 tuning](https://docs.nav2.org/rolling/configuration_and_development/tuning_guide/)
разделяет точное path following и local obstacle controllers. Поэтому карта видов
не заменяет свежую оценку препятствий.

У [DriveNet](https://github.com/Shotbylu/DriveNet-AI-for-Autonomous-Gaming) опубликованы
human video+key input, first-person GTA V/GPS и action accuracy. Это полезный
community пример сбора данных, не подтверждение Android/Black Russia arrival rate.
Код этих проектов не копировался и модели не скачивались. Более широкий разбор
и первичные исследования — в [предыдущем обзоре](../2026-10-23/NAVIGATION-METHODS-CAPTURE-RESEARCH.md).
