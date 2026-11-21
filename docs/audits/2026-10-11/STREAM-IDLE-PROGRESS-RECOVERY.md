# Неподвижный экран, зависание renderer и следующий APK55

11 октября 2026. Source-кандидат `5223998002451b935a25e01f1034b727561588bd`.
**Новая установка не выполнена.** На 3015 и Tuna остаются UI/API `6ee80c1f`;
последний readback подтверждает 15 устройств с APK54, включая PH030.
Этот этап не объявляет production, localhost/LAN/WAN или задержку принятыми.

## Воспроизведённые причины

1. Planar encoder повторял сохранённые исходные I420-пиксели только при запросе
   keyframe. После первого изображения viewer больше не требовал такого запроса;
   неподвижный Android producer мог оставлять encoder без следующего кадра.
2. Primary WebRTC viewer имел deadline первого изображения, но не контролировал
   последующую отрисовку. ICE/DTLS, echo и статистика могли продолжать приходить
   при остановившемся renderer. Формально active peer подавлял server decoder.
3. Capture/render/encode FPS не показывали возраст последнего исходного кадра
   и не отличали повтор сохранённых пикселей от нового захвата Android.
4. Предварительная сверка установщика выявила отсутствующий допуск двух модулей
   telemetry. Без исправления готовый серверный образ был бы отклонён до установки.

Это воспроизведение по source и fixtures. Оно не устанавливает одну общую причину
всех наблюдавшихся пользователем задержек, обрывов ICE и остановок MediaProjection.

## Поведение APK

Planar path использует уже принадлежащий encoder I420 cache. Если после успешной
подачи исходного кадра прошла одна секунда без следующей подачи, в MediaCodec
подаются эти же raw pixels с новым строго возрастающим PTS. Старые H.264 bytes
не переотправляются: codec создаёт новый access unit в своей reference chain.

При занятом codec хранится ровно один pending refresh. Новая исходная картинка
или явный keyframe request имеют приоритет; input callback завершает ожидание
без очереди копий. Ошибка с неизвестным результатом queueInputBuffer завершает
старый codec path, а не повторяет ту же неопределённую операцию.

CPU Surface fallback использует принадлежащий session Bitmap и уже существующий
ImageReader Handler. Последняя успешно posted picture повторяется не чаще одного
раза в секунду. До первого кадра, после failed copy/post и после stop её повтор
запрещён. Timer удаляется до освобождения Bitmap; obsolete session callback не
пишет в новый захват. Новые capture threads, MediaProjection, screenshot files,
неограниченные очереди и покадровые логи не добавлены.

Режим не заставляет статичный экран захватываться 30 раз в секунду и не является
доказательством свежести содержимого Android. Экспериментальный GPU/OES bridge
этим idle refresh не изменён; его отдельная native acceptance остаётся необходимой.
Активная картина по-прежнему поступает от настоящего producer и проходит FPS gate.

## Поведение веба и управления

После первой успешно представленной и связанной с capture картинки primary
viewer проверяет прогресс presentation. Если видимая вкладка шесть секунд не
получает следующей presentation, причина `video_frame_timeout` завершает exact peer.
ICE-connected, inbound RTP counters и echo не продлевают этот deadline.

Старый control endpoint отзывается, renderer очищается, DeviceStream возвращает
server decoder и запрашивает fresh keyframe/SPS/PPS. Следующая primary попытка
автоматически создаёт новый peer и grant по существующему bounded backoff:
1/2/4 секунды, после четырёх отказов — 60 секунд server fallback. Hidden viewer
и retired generation не запускают восстановление и не принимают поздний кадр.

DOWN/MOVE/UP не переотправляются через резервный маршрут. При потере ownership
нужны штатные native RELEASE/CANCEL и STARTUP нового controller. Один network
timeout не подтверждает, что Android освободил удерживаемое касание.

Предупреждение о старом изображении не скрыто косметически. Исправляется отсутствие
прогресса, а реальные пробелы capture и presentation остаются видимыми.

## Метрики и совместимость

APK heartbeat schema2 получает четыре optional scalar поля:

| Поле | Значение |
| --- | --- |
| `last_capture_age_ms` | Возраст последнего прочитанного producer image в момент APK snapshot |
| `last_render_age_ms` | Возраст последнего **свежего исходного** кадра, поданного encoder |
| `last_encoded_age_ms` | Возраст фактического codec media output; config NAL сюда не входит |
| `idle_refresh_frames_total` | Число принятых подач сохранённых raw pixels в текущем capture |

Idle submission не увеличивает capture/render FPS и не обнуляет source ages.
Реальный encoded callback увеличивает encoder FPS. После stop/reset ages неизвестны,
а session counter равен нулю. Это stage freshness, не measurement capture-to-display.

Backend проверяет strict integer bounds: ages0..86 400 000ms, counter0..2^53.
Отсутствующие значения старого APK сохраняются как unknown. Четыре per-device
Prometheus gauges действуют в single-process development profile: прежняя серия
удаляется при отсутствии нового измерения и при очистке device metrics.
В production multiprocess profile эти snapshots не экспортируются в Prometheus:
они остаются в bounded Redis diagnostics/history API. Это существующая политика
`device_gauge`, исключающая неснимаемые device labels между worker processes;
нулевые значения вместо отсутствующего измерения не создаются. Fleet alerts по
этим четырём значениям ещё не подключены. Session ID labels не добавлены.

Диагностика возвращает эти поля в существующем DTO. History принимает только
новую enum-причину `video_frame_timeout`; лимиты10 sessions/device,32KiB/session,
15samples/category и7d не изменены. Frames, IP, SDP, payload касаний и exception text
не добавляются в journal. Четыре поля также сохраняются через существующие
`agent_samples`: observer берёт проверенный DTO и сохраняет исходное время snapshot,
не превращая старый отчёт в свежий при повторном чтении. Веб продолжает показывать source, encoder, browser decode
и presentation как отдельные участки; echo/network RTT не выдается за video latency.

## Проверки

- Browser regression до исправления падала: первый кадр + продолжающиеся connected
  statistics оставляли frozen peer active. После исправления он завершается через6s,
  channel отзывается, late frame игнорируется, fresh attempt начинается автоматически.
- Отдельный test представляет неизменную картинку раз в секунду30s без кликов:
  такой поток не перезапускается.
- Основные frontend transport/control проверки:7 suites/274 tests. TypeScript и
  scoped ESLint прошли. Эти fixtures не являются native или browser runtime soak.
- Серверная WebSocket suite:695 tests/44 subtests; diagnostics/API/telemetry scope
  дополнительно прошёл89 tests. Ruff, mypy и generated OpenAPI reconciliation прошли.
- Installer regression до исправления отклоняла два reviewed telemetry modules.
  После исправления58 operational tests/151 subtests сохраняют dependency/schema,
  image/source, ownership и volume-health ограничения.
- История прошла45 tests. Нагрузочная fixture с максимальными счётчиками и ages
  сохраняет последние stage measurements, успешно закрывает сеанс и остаётся
  в прежнем лимите32KiB после25 report rounds.
- Current-state checker и37 его regression tests прошли после сверки:447 Markdown
  documents,279 dated evidence,20 chat requirements. Product остаётся9 accepted /
  41 open; новая подготовка не закрывает runtime или production критерии.
- Android lifecycle/codec fixtures добавлены для busy input, PTS, first frame,
  stop/late callback, uncertain queue failure и source-age/reset. Результат Android
  CI фиксируется отдельно; локальная Gradle-сборка на повреждённом C: не запускалась.
- Первая Android CI попытка source2d7464c4 выявила Kotlin expression error в idle
  worker. Исправленный source d487902d явно возвращает Unit из side-effect block.
  Предыдущая failed попытка не выдаётся за проверенную APK-сборку.
- Следующая попытка d487902d воспроизвела ошибку самого lifecycle test: `idleFor`
  вызывался на уже закрытом Looper. Source4d24d1e9 сохраняет реальный scheduled
  Runnable и проверяет поздний вызов после stop и после нового start; устаревший
  callback не рисует и не планирует работу в новой session.
- Source52239980 добавляет в CI именно совместный профиль будущего pilot APK:
  WebRTC + planar CPU input + continuous input, GPU bridge выключен, public STUN,
  dev package suffix `.pilot`. Проверяются dev/enterprise debug unit tests, lint
  и сборка. Disposable CI signer и fixture bootstrap не подходят для OTA стенда.

Все три workflow source522 завершились `success`. Android ordinary JUnit:
четыре варианта по1033 записи,0 failures/errors и1 skipped. Совместный профиль:
dev/enterprise debug unit tests, lint и assemble прошли; архив содержит JUnit
dev debug:1038 записей,0 failures/errors,1 skipped. Число enterprise tests
отдельно не заявляется: XML этого совместного варианта в архив не включён.
Digest обоих Android report archives и backend reports сверены с GitHub при
чтении в RAM. Backend JUnit:4028 records,43 skipped,0 failures/errors; веб:
154 suites/2226 tests,26 HTTP pages и73 client assets. HTTP packaging probe
не выполняет browser hydration и Android control. Большие image archives и
CI APK на C: не сохранялись. Новая worst-case history fixture проверена локально
после source522 и фиксируется отдельным последующим test/docs commit.

[Точные версии, CI и границы результата](STREAM-IDLE-PROGRESS-RECOVERY.json).

## Основания выбора

[Android MediaFormat repeat option](https://developer.android.com/reference/android/media/MediaFormat#KEY_REPEAT_PREVIOUS_FRAME_AFTER)
применяется только к Surface input и обещает однократный повтор. Он не обеспечивает
непрерывную подачу planar buffers; поэтому выбран ограниченный raw refresh в owner path.

[Parsec stream diagnostics](https://support.parsec.app/hc/en-us/articles/32381603663636-Stream-Overlay-Stats-and-Logging)
разделяет capture, encode, decode и network latency и допускает увеличенный frame
interval при малом visual change. Наша реализация сохраняет это различие и добавляет
явный idle counter, вместо вычисления «задержки видео» из одного echo RTT.

[WebRTC TURN guidance](https://webrtc.org/getting-started/turn-server)
описывает резервный relay для NAT/firewall, где прямой ICE path недоступен. Host-first
ICE срабатывает только для достижимой пары; один и тот же ПК не делает Android guest
тем же сетевым localhost, что браузер. TURN на текущем стенде ещё не настроен.

## Установка и следующий фактический допуск

Windows preflight16:39 UTC: C: `Warning / Full Repair Needed`; disk headroom около
42.22GiB. Блокирует состояние NTFS, а не нехватка RAM или диска. Сама Windows не
запрещает запуск компилятора: наша проверка не допускает heavy writes и замену
runtime поверх уже подтверждённых повреждений. Причина повреждения SSD/NTFS не
установлена. [Ремонт и backup](HOST-REPAIR-1216.md).

Пользователь выбрал ручную перезагрузку позже. Она здесь не выполняется; repair
не считается завершённым. Новые code/tests сохранены в GitHub. После ремонта нужны
fresh volume preflight, восстановление повреждённых Git objects и проверка fsck.

Подготовлен локальный source-pinned helper `.local-pilot/build-idle-apk55-20261011.py`.
Он требует успешные CI всех компонентов и совместного Android profile, совпадение
Android subtree, чистый fsck, version10255 и прежний signer. Его режим `--preflight`
в16:35 UTC подтвердил только `volume_not_ready`; compiler, создание candidate APK,
OTA и замена контейнеров не запускались. Enrollment и signing keys в GitHub не
передавались. Проверяется syntax helper; это не доказательство завершённой сборки.

Затем: exact reviewed UI/API image admission; signed/configured APK55 canary с
прежним pilot package/signer; PH010, затем PH025. Проверить60s неподвижного экрана,
физическое изменение Android вне веба, direct presentation stall→fallback→fresh peer,
удерживаемое касание при потере канала, новое STARTUP и обычный click после reconnect.
Оба web origin должны дать один revision и одинаковые JS/CSS assets.

Распространение APK55 начинается после canary/hash/receipt readback. PH030 получил
APK54 по ранее выданному grant: completed receipt и installed SHA подтверждены;
native stream/input acceptance на ноутбуке этим не выполнена. Ещё шесть эмуляторов
offline без команды на новую установку. [Новый readback APK54](APK54-FLEET-FOLLOWUP.json).
Затем нужны длительный soak, localhost/LAN/WAN с реально
selected candidate pair и TURN fallback. Это не обещание «100% прямой связи без
любого сетевого ограничения» и не стабильный release1.3.0.

[Рабочий реестр](../../operations/WORK-STATUS.md) ·
[Последняя APK54 доставка](APK54-FLEET-DELIVERY.md) ·
[Предыдущее восстановление канала](DIRECT-CHANNEL-RECOVERY.md).
