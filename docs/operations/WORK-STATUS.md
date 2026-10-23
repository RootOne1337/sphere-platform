# Работы, требования пользователя и границы приёмки

**24 октября — web teaching / кандидат APK89.** Реализован интегрированный режим
записи из карточки/потока: WASD, независимая камера/кнопка, original H264+native
journal, локальная библиотека и покадровый viewer. Multi-contact opt-in требует
новой APK; source/runtime acceptance различаются. После перезагрузки host guard
прошёл (~21GiB available), выполняется локальная проверка/упаковка. Предыдущие
runtime88/UI/API не выдаются за обновлённые. [Инструкция](TEACHING-WEB.md) ·
[Проверки и открытые допуски](../audits/2026-10-24/WEB-TEACHING-CONTACTS.md).


**Проверенная установка:** UI `a239baa2` / API `1afdc529`.

**24 октября — worker0.8.1: уточнение keyboard teach readiness.** Добавлен bounded
read-only inspector LDPlayer metadata, macros остаются данными. Найден referenced
recommended profile26 bindings вместо пустого override.303 tests/Ruff passed.
Нынешний native input single-pointer; полному WASD+camera+jump нужен следующий
multi-contact actor/keymapper/journal. Это не отказ H.264 recorder и не готовое
полное ручное управление. Plan3.6 уточняет DPI320 при1080p,100% render для teach,
независимый low-quality repeat и2D debug/отдельную3D реконструкцию. Физических
действий0, APK/UI/API/VPN/настройки не менялись. [Данные и допуски](../audits/2026-10-24/LDPLAYER-KEYMAP-READINESS081.md).

**Предыдущий этап24 октября — worker0.8.0: первый исполнимый teaching pipeline.** Исходный H.264,
own native pointer journal, strict dataset/COMPLETE, локальная ручная панель,
ordered feature bundle/temporal progress и offline degraded-quality experiment.
295 tests/Ruff passed. Final real PH011137/137 decoded, max receive gap93,791мс;
ранний276-frame run имел gap367,097мс и не исключён из результатов.2 fake APPLIED
и safe Stop проверены браузером на fake Android. Позднее на реальном PH011 прошли
два жеста/14 APPLIED,один3016мс, COMPLETE/CLOSED; game disconnected. Ни gameplay
teaching, ни Android1080p60,
ни независимый low-render repeat, ни controller/объезд/arrival/fleet не приняты.
Plan3.5; product9/41/50 неизменён. APK88/API/UI/VPN/guards сохранены; новых CI jobs
нет. [Код, доказательства, команды и следующий допуск](../audits/2026-10-24/MOTOR-TEACHING080.md).

**Предыдущий этап23 октября — исследование навигации и обучающей записи.** План3.4 сопоставляет
teach-and-repeat, миникарту/дорожный граф, локальные controllers и свежие препятствия.
Предложен device video + input journal/clock mapping; native30FPS master отдельно
от5Гц runtime. Это design/research, recorder и новые physical policies не включены,
product acceptance не повышена. [Источники, capture gap и условия испытаний](../audits/2026-10-23/NAVIGATION-METHODS-CAPTURE-RESEARCH.md).

**23 октября — worker0.7.5: shared RGB и visual checkpoint primitive.** Один
immutable RGB безопасно разделяется независимыми потребителями; закрытие/epoch
инвалидируют слот. CPU ORB/RANSAC хранит ограниченные признаки без RGB. Явный
reference107010B прочитан в новой сессии:50/50 matches; совместный P2P shadow:
74 ответа за~15с, receiver-age p95=198,084мс. Это не capture→APPLIED latency.
263 motor tests/Ruff прошли, finite clean exits подтверждены. Ранний observer
имел gap1,02с/min1, причина не установлена. Ни graph/pose/free-space, ни goal-conditioned
движение/объезд/прибытие/fleet не приняты. AFK-экран может совпадать с reference:
перед физическим тестом требуется отдельный gameplay/goal preflight; после перезахода
маршрут ставится заново. APK/VPN/API/UI и guard не менялись, новых CI jobs нет.
[Квитанция и следующий физический допуск](../audits/2026-10-23/MOTOR-ROUTE-VIEWS075.md).

**23 октября — worker0.7.4, generic perception boundary.** Direct FP32 object
observer PH011:125/75 свежих результатов за25/15с, минимум5 в полной секунде,
receiver-age p95 около104/115мс. На6 fixtures FP32 GPU близок CPU, FP16 этого
pipeline отклонён. Слабая ограда и ложные launcher detections не допускают
obstacle/free-space provider к управлению.241 tests/Ruff прошли; physical actions0.
Добавлены exact-RGB/runtime fingerprint checks; ни unknown, ни пустые detections
не дают free side. Один завершённый pilot потребовал scoped outer-process cleanup;
отдельный receiver получил setup deadline без кадра. Shutdown/reconnect открыты.
[Доказательства и полный список gap](../audits/2026-10-23/MOTOR-PERCEPTION074.md).
На момент0.7.4 visual route memory была проектной; частичный view-компонент0.7.5 описан выше.
APK/VPN/UI/API не менялись, новых GitHub jobs нет; product acceptance не повышена.

**23 октября, поздний срез — память и neural inference восстановлены.**
Один measured clean-pagecache reclaim WSL, без рестартов/сброса dirty/anonymous,
дал80,00→65,82GiB Windows commit после отложенного возврата памяти. Это не14GiB
освободившейся физической RAM. Все14 контейнеров сохранили start/health, guard85%
сохранён. На игровом PH011 P2P150M дала124 shadow results за~25с, минимум5 в полном
секундном окне; receiver-age-at-result p95=232,931мс. Ввод0 и goal conditioning0.
Qwen0.8B/2B действительно запущены, но не прошли opposite-goal grounding;2B
ошиблась на ограде/отсутствующем изображении. К управлению не допущены. Worker0.7.3
валидирует semantic refusal, lineage/active goal/deadline;231 tests/Ruff прошли.
Аutonomous A→B/recovery/arrival и fleet capacity остаются открытыми. APK88/API/UI
сохранены; новых GitHub jobs/Android builds нет. [Факты и следующий допуск](../audits/2026-10-23/MOTOR-MEMORY-RECOVERY073.md).

**23 октября — PH011 APK88/AWG2; worker0.7.2 и конечная ходьба.**
Адресная OTA и свежий package SHA10288 подтверждены. Уникальный AWG2 peer,
provider endpoint без дополнительного PC relay; kernel proof исключает Sphere UID10082
из app UID ranges, IPv6 приложений заблокирован. PH011 reboot/system UIDs/полный
VPN soak не приняты. Парк: APK85×2,APK88×2;17 offline не обновлены.
Первый20-с GPS runner упёрся в ограду; остановка была по времени. Конечный
операторский обход вывел персонажа на траву. Исправленный flow/аналоговый стик:
590→582м за8с,5,125Гц,max gap214,334мс,8/8 APPLIED/CLOSED. Autonomous obstacle
avoidance, jump/camera integration и arrival открыты.221 motor tests/Ruff прошли.
Qwen3.5-0.8B скачана и загружена в Vulkan/CPU, P2P150M прошла startup; все текущие
inference остановлены неизменным85% commit guard, predictions0. Чужие процессы
не остановлены, новых GitHub jobs/Android builds нет. Это CV, не neural navigation.
[Факты, скриншоты и следующие проверки](../audits/2026-10-23/PH011-APK88-MOTOR-CALIBRATION.md).

**23 октября — APK88 установлен; автоматический VPN restore проверен реальным reboot.**
Локальная последовательная сборка source `6ad0df5f`, lint и шесть unit-вариантов
прошли: 7684 исполнения, 18 skipped, 0 failures/errors. Полный release/denial CI
для этого дерева не заявляется; новые GitHub jobs не запускались, RAM guards сохранены.
Адресная OTA и SHA пакета подтверждены только на PH030. После одного настоящего
ACTIVE reboot восстановлены та же зашифрованная VPN-сессия и guard с новым boot ID;
действующие маршруты и HTTPS/выход `64.145.94.74` проверены независимо.
Прямой PC-поток около 55 FPS, 5 RGB-наблюдений/с и один 3-секундный жест с шестью
native receipts и освобождением подтверждены после загрузки; ИИ не запускался.
WinError5 шлюза исправлен, 16 изолированных tests/Ruff прошли. Шлюз временный,
зависит от ПК и истекает 24 октября в 00:08 UTC+5 без продления.
Ранний boot kill switch, system UIDs, телефонный браузер, прямой Android WAN,
paused/disabled physical reboot и общая production VPN-приёмка остаются открытыми.
Обычный update-канал и остальные устройства не менялись.
[Точная область, доказательства и ограничения](../audits/2026-10-23/PH030-APK88-LOCAL-AUTOSTART.md).

Ниже — предыдущие датированные этапы; их конечные состояния могли измениться.

**23 октября — проверен расход RAM хоста без перезагрузки.**
Доступно около 10 GiB; измерены compression, paged/nonpaged pool и гостевая
память WSL. Контейнеры сообщают около 2 GiB; private bytes WSL не равны RAM.
Конкретный удерживающий драйвер не установлен. Resource guard дополнен
показателями ядра/процессов/дескрипторов, пороги сохранены; 49 tests и Ruff прошли.
[Квитанция и интерпретация](../audits/2026-10-23/HOST-MEMORY-DIAGNOSIS.md).
Остановившийся собственный LAN gateway восстановлен; свежие пакеты, handshake
и прежняя управляющая сессия PH030 подтверждены. Файл `running` был устаревшим.
Новая HTTPS/phone-input приёмка не заявляется. APK87 выполняет полный облачный
CI39844420660 на Android-дереве кандидата; installed APK остаётся 86.

**23 октября — уточнена причина блокировки ввода и проверен прямой PC-путь.**
Собственная packet-observation команда через общий SHELL превысила 5 с и
установила persistent unknown flag; следующий native handoff закономерно
заблокировал ввод. Ограждение не обходилось. Независимый capture-only headless
с активным VPN получил 780 кадров за 15 с и 75 RGB-наблюдений (4,995 Гц)
напрямую по UDP без команд ввода. Это не приёмка телефонного браузера:
его ICE по-прежнему не принят. APK87 остаётся кандидатом; полный CI выполняется.
[Расследование, точная область и следующий допуск](../audits/2026-10-23/PH030-STREAM-VPN-INCIDENT.md).

**23 октября — AWG2 работает на PH030 через LAN-шлюз; стрим выявил дефект.**
Chrome показал VPN-IP, HTTPS по IP и имени прошёл под UID игры, собственный
UID Sphere сохранил отдельный выход. Guard блокирует приложения при паузе
и активном TUN с остановленным шлюзом; повторный запуск шлюза восстанавливает
трафик. 11 свежих снимков за 901,8 с подтвердили сетевой canary. Это зависит
от ПК/его существующего VPN и аренды шлюза до 24 часов. Прямой Android WAN
ещё не работает. Один дополнительный AWG peer создан после разрешения;
только его awg1 переведён с upstream 105 на 100. Старый WG peer неактивен,
не удалён из-за `FORBIDDEN_DELETE`; соседние серверы не менялись.

Пользователь подтвердил игру, два native снимка показывают игровой мир.
Дальнейшая проверка экрана остановилась: при подключении телефона в той же
LAN нет ответов ICE, а ввод перешёл в `root_handoff_unknown` / `cleanup_unknown`.
Полная 15-минутная игровая сессия и совместимость VPN со стримом не приняты.
APK87 `001fd1a3` исключает VPN из ICE и лишнюю FIFO-проверку root-shell без input;
полный GitHub Android CI выполняется (39844420660), установки ещё нет.
Проверки неопределённого освобождения не ослаблялись. Три диагностических
файла на Android ожидают уборки после восстановления; gateway работает.
[Квитанция](../audits/2026-10-23/PH030-AWG2-LAN-GATEWAY-CANARY.md) ·
[Эксплуатация шлюза](VPN-LAN-GATEWAY-CANARY.md).

Ниже — предыдущие датированные этапы; их конечные состояния могли измениться.

**22 октября — backend и APK86 установлены, guard широкого режима проверен.**
API `1afdc529` заменён без миграции и исключений resource guard. APK86 адресно
установлен на PH030, hash подтверждён; остальные три online остаются APK85.
Plan 5 исключает UID Sphere, обе IP-семьи приложений блокируются при паузе,
Sphere control session сохранён. Обычный WG и client-junk A/B не дали HTTPS.
Переход на существующий AWG1 остановлен: API вернул `FORBIDDEN_DELETE` при
удалении собственного тестового peer. Дополнительный AWG peer не создавался;
ожидается выбор пользователя. Данные игры сохранены, её enabled state восстановлен.
[Canary и точное состояние](../audits/2026-10-22/VPN-APK86-ALLAPPS-PH030-CANARY.md) ·
[Контракт WG Router](../design/WG-ROUTER-PROVIDER-INTEGRATION.md).

**22 октября — пользовательский WG на PH030, оставлена защита.** Профиль
назначен Black Russia, Sphere вне туннеля. TCP/TLS доходят до приложения;
последующие отправки видны в TUN и UDP на `wlan0`, ответа нет. Приоритетный A/B
не улучшил HTTP/DNS, оригинальные правила восстановлены. Причина внешнего сбоя
не доказана. PH030 оставлен `PAUSED_GUARD_HELD`: обе IP-семьи игры заблокированы,
туннель закрыт, control сохранён. Временные файлы/relay убраны. Независимый host
probe подготовлен, но не собран из-за штатного commit guard. Правки веб-подписей
прошли 85 VPN tests и ещё не установлены. Следующий исходный кандидат уже
реализует UID ranges; физические проверки новых установок/reboot остаются открыты.
[Тест и состояние](../audits/2026-10-22/PH030-WG85-PATH-INVESTIGATION.md) ·
[Новый режим](../design/VPN-ALL-EXCEPT-SPHERE.md).

**22 октября — APK85 установлен на всех четырёх online pilot-устройствах.**
PH010/PH011/PH025/PH030 завершили OTA, независимый SHA установленного пакета
проверен на каждом. 17 offline не обновлены. Полный hosted CI: 1277 тестов
на debug-вариант, 0 failures/errors, 1 skip; настроенный APK также собран в GitHub
с зашифрованным artifact и переподписан локально без изменения 936 payload entries.
WG-профиль/закрытые ключи подписи не уходили в CI; одноразовый secret удалён.
На PH011 plan 4 прошёл 12+5 HTTP-ответов с отдельным локальным AWG1 peer,
pause/resume, crash isolation, явный disconnect и kernel cleanup. Основной Sphere
сохранял связь; тестовые профили архивированы, оснастка удалена. Внешний WG остаётся
нестабильным после первых TCP, DNS не принят. Production journal/leases, IPv6,
длинная нагрузка и общий executor остаются открытыми.
[Поставка и экраны](../audits/2026-10-22/VPN-APK85-CLOUD-AND-ADDRESSED-DELIVERY.md) ·
[Физическая проверка](../audits/2026-10-22/VPN-APK85-MAIN-CANARY.md).

**22 октября — API исправлен в установке; PH011 выявил mark-дефект APK84.**
Повторный ресурсный допуск прошёл; API `cd2431e2` установлен без schema/OTA
изменений. RPC snapshot совпал с `/vpn/runtime`, проверены реальные desktop/mobile
экраны. В основном APK84 handshake подтверждён, но TCP/DNS тестового UID не проходили.
Без дополнительной mark трафик заработал; после её возврата ошибка повторилась.
Pause блокирует только выбранное приложение, Sphere сохраняет связь. Disconnect,
kernel cleanup и восстановление обычной сети подтверждены, профиль архивирован.
APK85 (`79ba84f9`, plan 4 без mark) отправлен в hosted CI, установка ещё не выполнена.
[Доставка API](../audits/2026-10-22/VPN-STATUS-ROUTING-LIVE-DELIVERY.md) ·
[Физический опыт](../audits/2026-10-22/VPN-APK84-MAIN-CANARY.md).

**22 октября — исправление доставки VPN-статуса прошло полный CI.** На PH011
зафиксирован ответ основного APK84 `IDLE` с отдельным PID `:vpn`; API baseline
сохранял `observation=null`. Исправлен пропуск `app_vpn_status` в реальном receive
loop. 4428 passed, 107 skipped, 668 subtests, coverage 82,57%; шесть jobs успешны.
Два прежних gateway tests падали из-за ECR data quota; canonical Docker Hub
с тем же независимо проверенным digest восстановил проверки.
Образ загружен/проверен, но первый допуск остановил замену API по commit headroom.
Старый API healthy, его ID не поменялся; повторный импорт не требуется.
[Build-only квитанция](../audits/2026-10-22/VPN-STATUS-ROUTING-CI.md).

**22 октября — APK84 установлен на PH011.** Штатный адресный OTA завершён после
перезапуска процесса, независимый SHA пакета совпал. Полный Android CI успешен;
Android/native-builder source идентичен подписанному локальному артефакту.
CI-подпись отличается и не устанавливалась. PH030 offline, его обновление не
запускалось. Физическое применение VPN остаётся отдельной проверкой.
[Точная поставка](../audits/2026-10-22/VPN-APK84-PH011-DELIVERY.md).

**22 октября — пакетный импорт установлен, ответ после commit потерян и восстановлен.**
API `4a6ada92` / UI `46dd02ff` получены из успешных hosted CI: 4422 backend tests,
107 skipped, 668 subtests, 82,58% coverage; 2630 frontend tests / 183 suites.
Schema head сохранён; при каждой установке не менялись 45 других контейнеров.
Реальный сайт проверен на 1440×1000 и 390×844: 100 файлов, ошибка №37, строка 100,
закреплённые действия. Один сохранённый пакет из двух synthetic profiles восстановлен
после искусственного обрыва ответа одним status-запросом без второго save. Поздний
конфликт откатывает новую строку; оба тестовых профиля архивированы. APK83 показывает
неизвестные native counters; физический VPN этим проходом не менялся.
[Квитанция и шесть скриншотов](../audits/2026-10-22/VPN-BATCH-LIVE-DELIVERY.md).

**22 октября — новый этап: массовый импорт, hosted CI и план управления VPN-парком.**
В исходниках реализованы до 100 `.conf` одним пакетом, предварительная проверка,
атомарное сохранение и read-only status по прежним ID при потере ответа.
26 backend tests, 13 UI tests и TypeScript прошли; добавлены реальные PostgreSQL
сценарии 100 imports/minimal-role RLS, overlapping batches и late conflict rollback.
Backend mypy проверяет все 279 source files без ошибок после исправления типов
каталога и runtime freshness. Полный local CI остановился до checkout по Windows
commit headroom; память пользователя/эмуляторы не освобождались.

Android workflow расширен закреплённой native WG/AWG сборкой трёх ABI и проверкой
single-APK canary/release denial; полный прогон перенесён на GitHub. Backend/web
также получили ручной hosted запуск. Их конечные результаты/установка будут
записаны отдельной квитанцией; старт workflow не считается успехом или OTA.
README переработан, прежний полный текст сохранён в истории. Исследованы три
смежных VPN-репозитория и Android accounting/proxy ограничения.
[Контракт импорта](VPN-PROFILES.md), [план с источниками и условиями приёмки](../design/VPN-FLEET-CONTROL.md).

**22 октября — новый VPN workspace и зашифрованный каталог установлены.**
На `localhost:3015` обновлены UI/API и применена добавочная миграция
`20261021_vpn_profiles`. Каталог использует отдельную ограниченную DB-роль;
основная роль API, фоновые задачи и другие контейнеры не перенастраивались.
Подтверждены actual login/RLS и live HTTP import/replay/import-status/revision/
history/archive. Синтетический профиль приёмки оставлен в архиве; на устройства он
не назначен. Конечное продолжение после остановки по памяти использовало сохранённую
успешную migration receipt, повторной миграции/смены пароля не было.

Установленный сайт проверен Playwright на 1440×900 и 390×844: все четыре вкладки,
импорт, диагностика PH030 и история реального тестового профиля. Ширина документа и
мобильного dialog 390 px, console errors/warnings в авторизованном проходе 0.
Сохранены восемь скриншотов, собственный QA-браузер закрыт. Это не аппаратный touch
тест и не приёмка Android VPN. На APK83 UI показывает отсутствие отчёта/необходимость
обновления; успешный heartbeat не заменяет статус сервиса. Старые образы сохранены.
APK84, OTA, native service fault pilot и server journal/leases остаются открытыми;
физические VPN и игры этим обновлением не менялись.
[Результат и скриншоты](../audits/2026-10-22/VPN-CATALOG-LIVE-DELIVERY.md),
[квитанция](../audits/2026-10-22/VPN-CATALOG-LIVE-DELIVERY.json).

**21 октября — VPN: веб и API-образы допущены; изоляция каталога и recovery проверены.**
Веб `37926bd3` прошёл packaged HTTP проверку 26 страниц/72 assets. API `7d2a6846`
прошёл полный новый backend CI: 4440 passed, 63 skipped, 659 subtests, coverage
82,49%; GitHub status подтверждён. Его образ прошёл runtime/restart и multiprocess
metrics probes. Ранее прерванные упаковки продолжены с проверкой исходников/образа,
без повторного tag/rebuild, заимствования неуспешного probe или ослабления guard.

Добавлено отдельное подключение каталога `VPN_PROFILE_POSTGRES_URL`: nonowner login,
проверка фактического RLS/grants/tenant на каждом запросе; fallback на основную роль
запрещён. Старые фоновые задачи, стрим и роль всего API этим не перенастраиваются.
45 targeted реальных DB tests и 299 профильных/packaging tests прошли. Снята приватная
копия текущей БД; полное восстановление в собственной БД, миграция и HTTP lifecycle
с минимальными grants прошли, числа строк шести прежних таблиц сохранились.
Новые секреты сохранены только в приватной области; независимое чтение/recovery
проверены, в рабочий API они ещё не добавлены. Off-host recovery не подтверждён.

Подготовлен отдельный migration/install worker с откатом API на прежний образ и
сохранением добавленной схемы. Его точный конечный путь ещё не принят: повторные
изолированные проверки прерывались до выполнения worker по RAM/commit headroom.
Обычный schema-free installer не расширен. Рабочая БД/UI/API/APK не заменены;
single-APK pilot и server operation journal/leases остаются открытыми.
[Квитанция текущего этапа](../audits/2026-10-21/VPN-CATALOG-DELIVERY-PREPARATION.json).

**21 октября — VPN workspace: полный повторный CI успешен, rollout открыт.**
Source `37926bd3`, run `20261021T155852Z-b40e9952`: frontend 2606/180 suites,
backend 4399 passed, 63 skipped и 645 subtests; coverage 82,46%. Миграции проверены
в изолированных сервисах, после прогона они удалены. Прежнее performance failure
не повторилось, лимит 200 мс не менялся. GitHub local CI statuses опубликованы.
Веб Linux image собран, но не допущен: перед packaged HTTP probe запас commit
памяти снова превысил существующий порог. Первая попытка сохранена, повтор через
build cache дал тот же image ID. Guard не ослаблялся; UI/API/APK не установлены.
Полный Android CI требует 12 GiB свободной RAM; запрос владельцу об освобождении
памяти остаётся открытым. Каталог/API migration/key recovery, runtime DB role,
main-APK VPN pilot и общий operation journal остаются следующим этапом.
[Квитанция итогового прогона](../audits/2026-10-21/VPN-WORKSPACE-REGRESSION.json).

**21 октября — APK84: повторная локальная debug-сборка прошла.**
Source `7f06701e`: Dev/Enterprise assemble и lint успешны; в каждом debug-варианте
1275 tests, 0 failures/errors, 3 skipped. Подпись совпала с прежней pilot-подписью;
native WG/AWG трёх ABI внутри APK сверены по SHA. Исправленная конфигурация test
workers прошла оба полных debug-набора. Artifact version 10284, SHA
`33916fa4f605afbbd62e2b76032b8c7b51184ef919afff50f9e3c2ce88c2b7b0`.
Это локальный кандидат: полный Android CI/release/canary admission, OTA и реальный
single-APK VPN pilot не подтверждены. UI/API/APK на устройствах не заменялись.
[Квитанция сборки](../audits/2026-10-21/VPN-APK84-LOCAL-BUILD.json).

**21 октября — VPN: квитанции назначения без config/QR в кэше веба.**
Хук legacy assignment проверяет привязку device ID, сохраняет только метаданные
назначения, очищает Axios error до HTTP status и запрещает автоматический retry.
76 тестов VPN UI/hooks прошли, в том числе три новых проверки кэша и чужой квитанции.
Старый HTTP API всё ещё может отдавать config/QR другим клиентам; серверный контракт
и установленный runtime этим изменением не заменены.

**21 октября — APK84: первый полный debug-прогон не принят.**
На Android source `61df5729` assemble/lint завершились, но unit worker с default
heap 512 MiB после 1262 выполненных тестов сообщил устаревший count assertion
и два OutOfMemoryError. После OOM остановлен только принадлежащий этой сборке
test worker; результат сохранён как failure, APK не опубликован и не установлен.
Assertion заменён проверкой прежних wire names и JSON новых VPN-команд. Для
unit-задач задан один worker, heap 768 MiB и переразапуск после 40 классов;
это кандидат настройки тестов, ему ещё нужен новый полный прогон. Ограничения
host resource guard и допуск OTA не менялись.

**21 октября — переработка VPN workspace и визуальная проверка исходников.**
Подключения Android, библиотека профилей, инфраструктура и политика трафика разделены
вкладками. Переработаны карточки, поиск, состояния, импорт, диагностика, история версий,
архив и подтверждение сетевых операций. На телефоне строки устройств перестраиваются
без горизонтального вылезания; у длинной формы закреплены заголовок и действия.
Проверены реальные компоненты в neo-dark/sandstone, 1440×900 и 390×844, с локальными
шрифтами приложения и синтетическими данными. Исправлены вылезание IPv6 select,
слишком длинные мобильные действия и кратковременная ложная устарелость нового отчёта.
TypeScript, 61 VPN frontend test и 10 targeted backend tests прошли.
Предыдущий полный прогон `61df5729`: frontend 2600 passed; backend 4389 passed,
1 performance failure (203 мс при лимите 200 мс), 63 skipped. Отдельный повтор этого
теста прошёл без coverage; он не заменяет полный прогон конечного исходника.
Внутренний sealed-delivery helper протестирован, но ещё не подключён к HTTP/outbox;
server journal и lease остаются открыты. Установка UI/API/APK выше не менялась.
[Скриншоты и границы проверки](../audits/2026-10-21/VPN-WORKSPACE-REDESIGN.md).

**21 октября — VPN: единый APK и состояние по устройствам, исходный этап.**
Добавлены private Binder, изолированный процесс `:vpn`, pause/resume/rotate с сохранением
UID guard, durable device receipts и encrypted envelope. В новом VPN-процессе отключены
повторные startup root/worker/enrollment; монитор читает JNI без периодического `su`.
Исправлены Android fwmark/UID routing и обязательные PID/sample time в IPC.
Kernel fixture плана v3 подтвердил блокировку/reused TUN name/control UID/release,
cleanup завершён. API текущего WS-session и веб-диагностика реализованы; отдельные
серверные leases/journal, общий UI/script/orchestration execution и real-service pilot
остаются открыты. APK84 объявлен исходным кандидатом, не установленной версией.
Наличие исходников не меняет проверенную установку выше.
[Архитектура 1.3](../design/VPN-EGRESS-ARCHITECTURE.md).

**21 октября — VPN: Android SDK, kernel guard и конечные WG/AWG опыты.**
Закреплённый SDK, Go clock overlay и JNI lifecycle patch собраны для трёх ABI.
PH011 подтвердил native AWG/HTTP echo, PH030 — WireGuard handshake/DNS по профилю
владельца. В обоих опытах force-stop закрыл доступ выбранного тестового UID,
контрольный UID Sphere сохранил доступ; release и очистка подтверждены. Частый
root-опрос fixture завершён; его superuser toast учтён как дефект диагностического UX.
Это отдельные probe APK/root TUN, не приёмка `VpnService` в основном Sphere APK.
Единый service, журнал операций, scripts/orchestration и rollout остаются следующим
этапом. [Квитанция и ограничения](../audits/2026-10-21/VPN-ANDROID-PROVIDER-CANDIDATE.json),
[архитектура 1.2](../design/VPN-EGRESS-ARCHITECTURE.md).

**21 октября — VPN: зашифрованный каталог и нативный кандидат.** В исходниках добавлены
импорт, неизменяемые версии, поиск/архив, отдельный key ring и tenant RLS. Пройдены
178 backend/RLS/native-builder tests, 9 настоящих PostgreSQL concurrency/RLS tests
и 46 VPN frontend tests; TypeScript/Ruff прошли. UI визуально проверен на синтетической
странице 1440×900 и 390×844, у импорта закреплены заголовок/кнопки. Закреплённый AWG
собран для трёх ABI, x86_64 повторился по SHA; без Android suspend-clock patch это
только диагностические `.so`, не готовый SDK. Рабочая БД, UI/API/APK, VPN и игры
не менялись. Нужны release AAR/provider, UID guard, журнал применения и live fault pilot.
[Эксплуатация каталога](VPN-PROFILES.md),
[проверки и ограничения](../audits/2026-10-21/VPN-CATALOG-NATIVE-CANDIDATE.json).

**21 октября — VPN: изоляция управления и первый исходный этап.** Добавлены проверка
профиля WG/AWG1–3.1, явная политика выбранных приложений, capability API и окно
проверки на `/vpn`. Root-подключение/reconnect и глобальный kill switch в новой
Android-исходной версии заблокированы до изолированного провайдера. Это не установленный
Amnezia SDK и не рабочий live VPN. Нужны provider/AAR, UID/lockdown guard, секреты,
durable operation journal и отдельный пилот. [Архитектура и этапы](../design/VPN-EGRESS-ARCHITECTURE.md),
[проверки исходников](../audits/2026-10-21/VPN-PROFILE-ISOLATION.json).

**PH030: повторный вход через МТС снова завис по сообщению владельца.** Успешный первый
вход не подтвердил IP-only причину. Свежий снимок в 08:38 UTC застал уже стартовый
экран гостя VOLOGDA; APK83 отвечает, read-only состояние сохранено. Перезапусков,
сбросов, сетевых изменений и ИИ-действий не выполняли. Причина повторного входа открыта.

**21 октября — PH030: новый гость вошёл на VOLOGDA через МТС.** После выполненного
владельцем сброса и загрузки пройдены guest/создание персонажа; свежий native PNG подтверждает
игровой мир. Headless direct не установился, вход сделан резервными снимками/командами Sphere.
Модель не запускалась; стабильная сессия, повторный вход и быстрые RGB/control для ИИ открыты.
Изменились сеть, данные, аккаунт и сервер — IP/аккаунт-метка не доказаны. Пользователь
проводит ручной сетевой контроль. [Квитанция](../audits/2026-10-21/BLACK-RUSSIA-PH030-GUEST-ENTRY.json).

**21 октября — PH030: смена сети не восстановила повторный вход.** Пользователь подтвердил
первый вход и обрывы через домашний Wi-Fi, затем бесконечное подключение через раздачу МТС;
телефон на МТС в это время входит. Одной сетевой гипотезы недостаточно: первичный обрыв и
последующее зависание разделены, сохранённое клиентское состояние — гипотеза. Пользователь
повторно скачивает ресурсы; PH030 не трогали. Сохранённый официальный APK проверен без
изменений: ARM/ARM64 и литералы updater state/patch, без доказательства античит-метки.
Подготовлен и только валидирован read-only DAG13нод, device commands0; следующий шаг —
healthy baseline/первый обрыв/failed re-entry до нового reset. [Обновлённый разбор](../audits/2026-10-21/BLACK-RUSSIA-PH025-CONNECTION.md).

**21 октября — Black Russia PH025 и физический телефон.** Свежий PH025 зависает на
подключении, один полный stop/open не помог. BR/app повторно фиксирует MainThread stall
6021/6047мс; причина не установлена. Sphere direct echo≈18–22мс, это другой путь, не вход
в игровой мир. Найдены близкий отзыв19октября безVPN и ответ разработчика20октября;
официальные email/guest/anti-cheat ограничения проверены отдельно. S24 Ultra с периодическими
обрывами — сообщение пользователя: Пенза, Ростелеком/Wi-Fi с обрывами, МТС15–20мин
без них подтверждены владельцем. Следующий контроль PH030 через раздачу МТС, затем
домашний Ethernet; проверка PH030 и точный код отключения ещё открыты. Данные
игры не очищались, learned input не запускался; семь собственных diagnostic DAG архивированы
с сохранением версий/результатов. [Диагностика и следующие проверки](../audits/2026-10-21/BLACK-RUSSIA-PH025-CONNECTION.md).

**21 октября — общий игровой AI-план2.9.** Перепроверен приложенный разбор по первичным
публикациям/кодовым интерфейсам и пользовательским опытам. Уточнены цели без меток/миникарты,
capabilities/goal/skill contracts, ограниченная visual memory и G1–G6. Исправлены обещания
conditioning/latency/capacity и спецификация RX9070. Документ отделяет проектное от готового;
новые модели не скачивались. Последние три PNG — явно сохранённые кадры17октября;
24waypoint PNG=13.85MiB локально, не серверный архив. [Единый план](../design/MOTOR-AI-PLATFORM.md),
[research receipt](../audits/2026-10-21/MOTOR-GENERAL-GOALS-REVIEW08.json).

**21 октября — worker0.7.0, GPS-линия миникарты.** Реализованы отдельный bounded профиль,
связный path-distance lookahead и read-only CLI.184 motor tests/Ruff прошли. На20 архивных
изображениях получено18 контуров с неизвестным heading и2 отказа. Свежий PH025 CLI:
99 анализов/5.001Гц, минимум4 в полной секунде, ноль native команд; виден поиск Android,
не gameplay. A→B/проходимость/vehicle input/PH030 остаются открыты. Статус currentImplementation
приведён к0.7; исторический срез0.5 сохранён. [Измерения и ограничения](../audits/2026-10-21/MOTOR-MINIMAP-ROUTE070.md).

**20 октября — навигация A→B и worker0.6.1.** Обновлён единый AI-план2.7: GPS-route/
obstacle/vehicle contracts, удержание между наблюдениями, latency budget, компактные VLM,
границы VPN и порядок N1–N6. Добавлена bounded result-cadence telemetry;153 motor tests/Ruff
прошли. Настоящие PH025/RX9070 video-only опыты дали4.036/4.921Гц NitroGen16/P2P150M,
минимумы3/4 ответа в полных1-с окнах. Сцена — game disconnect; native input не запрашивался.
Цель в модели пока не передаётся; вождение/устойчивые5Гц/50 устройств не приняты.
Установка UI/API/APK сохранена. [Факты и ограничения](../audits/2026-10-20/MOTOR-NAVIGATION-REVIEW07.md).

**20 октября — веб5cbb и APK83.** Добавлены общий локальный ICE topology observer и отдельный Android input dispatcher. 2569 frontend tests; Android dev/enterprise lint/build/unit suites — по1252 теста,3 skipped. APK83 завершил OTA на4 online устройствах:3 package SHA сверены,PH030 — completed OTA/версия без отдельного hash;17 offline не обновлены. На PH030 подтверждены кнопки и жест, но повторное подключение в проверочном браузере осталось на серверном видео без управления. Снижение latency и VPN/reconnect production-приёмка открыты. [Изменения, отрицательные проверки и следующие условия](../audits/2026-10-20/NETWORK-ROUTE-INPUT83-DELIVERY.md).

**20 октября — worker0.6 и PH025.** Реализован общий opt-in model→held-stick исполнитель,
исправлены request/result binding и cadence; добавлены RTP recovery и scheduler/ACK/SCTP telemetry.
145 motor tests прошли. PH025: NitroGen/RX9070 в20-с video-only опыте дал89 ответов;
finite12-с movement-only опыт —61 ответ и62/62 APPLIED. Повторы выявили ACK/lease failures
и SCTP retransmissions с RTO1000мс. Для model executor ограничен срок ретрансляции200мс;
устойчивый gameplay пока не принят. Black Russia установлена/скачана, гостевой персонаж в мире CHERRY.
Цвета после нового capture восстановились, но причина прежнего искажения открыта. Данные
не стирались, UI/API/APK82 сохранены. [Код, результаты и границы](../audits/2026-10-20/MOTOR-PH025-EXECUTION06.md).

**17 октября — разобрано бесконечное подключение Black Russia.** На PH011 сама игра остаётся на загрузке при исправном прямом видео. Проверены версия16.110.18323, часы, свободное место, root-журнал и снимок сокетов; первопричина не подтверждена. Исследованы официальные описания CUS/авторизации и прежние ошибки входа. Пользовательский сброс кэша вместе с данными ещё не разделяет причины; в этой проверке данные не удалялись, игра/эмулятор не перезапускались, AI не запускался. [Факты, источники и контролируемая проверка](../audits/2026-10-17/BLACK-RUSSIA-CONNECTION-HANG.md).

**17 октября — ограниченные recovery-примитивы.** В основной код добавлены supervisor прогресса/падения/unknown scene, finite double-tap/camera sequences и optional OpenCV sensor.122 motor tests и Ruff прошли. Это не готовый обход зданий: perception и dispatch recovery ещё требуют integration, native multi-touch отсутствует. PH011 после AFK отключения/двух перезапусков игры/одного Android reboot остаётся на подключении; read-only guard подтвердил прямые кадры/ALIVE/CLOSED без физических действий. Положительная jump/camera calibration не выполнена. [Код, evidence и блокер](../audits/2026-10-17/MOTOR-NAVIGATION-RECOVERY.md).

**17 октября — пользователь подтвердил проход к метке.** Конечный CV visual servo на PH011:241→110→46→25м, затем метка/маршрут исчезли; пользователь подтвердил «добежала».296 наблюдений/5.126Гц,36/36 APPLIED, один непрерывный контакт и CLOSED. Без NitroGen/P2P; learned navigation и общий production SLA не приняты. [Квитанция и границы](../audits/2026-10-17/MOTOR-WAYPOINT-SERVO.md).

**17 октября — удержание стика и временная траектория.** Устранён rapid UP/DOWN в новом contact adapter; последнее45-с испытание NitroGen8 дало235 решений/5.182Гц,571/571 APPLIED и один непрерывный контакт. Все свои participants/GPU children закрыты. Около70% модельных состояний neutral; метка241→241м. Goal navigation не принята. P2P запускался без text conditioning, поэтому его пригодность по этому опыту не отвергается. [Результаты и следующие условия](../audits/2026-10-17/MOTOR-STICK-CONTACT-LIVE.md).

**17 октября — первый настоящий learned WASD тест.** Pixel2Play150M на RX9070:66решений,5,226Гц по последовательности; минимум5решений в полных1-с окнах.37ненулевых movement predictions,15/15native APPLIED; свой participant и GPU child закрыты. Только WASD, другие channels явно masked; это12-секундный private prototype, не навигация или production executor. [Результаты и ограничения](../audits/2026-10-17/MOTOR-LEARNED-WALK-PILOT.md).

**17 октября — worker0.5.1, свежий RGB и гостевой игровой мир.** Убрано старение следующего RGB во время медленного inference;85 motor tests прошли. Гость вошёл на TYUMEN, короткий ручной direct drag уменьшил маркер8→7м; native PNG/XPath подтверждают tutorial world. NitroGen/P2P повторно проверены в learned shadow без модельных физических действий. Полный игровой executor/preprocessing и общий gameplay SLA открыты. UI/API15ce/APK82 сохранены. [Результаты и границы](../audits/2026-10-17/MOTOR-PROCESS-POLICY051.md).

**17 октября — worker0.5 и общий локальный process provider.** NitroGen/P2P на RX9070 прошли direct PH011 shadow через versioned RGB pipe;84 motor tests прошли. Исправлен ложный отказ при закрытии GPU child; исходный отрицательный прогон сохранён. Загрузка Black Russia завершена, регистрация ждёт пользователя. Это экран регистрации, не gameplay; model loader/preprocessing, игровой профиль/multi-touch и отдельная GPU/LAN открыты. UI/API15ce/APK82 сохранены. [Код, результаты и границы](../audits/2026-10-17/MOTOR-PROCESS-POLICY05.md).

**17 октября — реальный локальный AMD inference.** NitroGen и Open Pixel2Play150M скачаны и запущены на RX9070 через прямые кадры PH011/Sphere. После исправления aiortc RTP buffer128→2048 прошли конечные86/233 inference responses; p50 decoded→reply246/146мс, server→worker video0. Исправленные прогоны видели disconnect renderer после inactivity, поэтому игровой executor/навигация не приняты.71 motor tests прошли. APK82/UI/API15ce сохранены; frontend keyboard focus fix проверен локально, ещё не установлен. [Среда, источники, задержки и отрицательные результаты](../audits/2026-10-17/MOTOR-AMD-LOCAL41.md).

**17 октября — worker0.4 и асинхронная shadow policy.** На PH011 по 75 ответов нейтральной заглушки на исходные RGB-кадры через3015/Tuna, около5Гц, без физических команд и серверного видео; отдельно6/6 точек native ввода. Исправлена гонка ACK при закрытии,68 motor tests прошли. Проверены исходники NitroGen, Nexto, MineStudio и VPT. Модель/GPU, игровые профили и gameplay ещё не подключены. [Реализация, источники и границы](../audits/2026-10-17/MOTOR-REALTIME-SHADOW04.md).

**17 октября — headless worker0.3 и конечный ввод.** На PH011 проверены прямые кадры без браузера и 6/6 native DOWN/MOVE/UP при локальном signaling и через Tuna; server→worker video0байт, RGB около5Гц. Исправлены ранняя availability APK и ложная ошибка штатного закрытия peer;46 motor tests прошли. Веб/API15ce и APK82 сохранены. Модель, игровые профили/multi-touch, отдельная GPU/LAN и gameplay ещё не готовы. [Готовность и следующие условия](../audits/2026-10-17/MOTOR-WORKER03-READINESS.md).

**17 октября — общая временная шкала APK82.** APK82 установлен по сверенным хешам на четырёх включённых устройствах; веб/API15ce сохранены на3015/Tuna. На PH011/PH030 проверены запись и повтор двух жестов с общей временной шкалой, сохранением двух direct media peers и возвратом ручного управления. Нагрузочный и общий production SLA не приняты. [Поставка и границы](../audits/2026-10-16/POINTER-TIMELINE82-DELIVERY.md). Автозапуски hosted CI отключены; автоматическая локальная очередь ещё открыта. [Исправление сведений о CI](../audits/2026-10-16/HOSTED-ACTIONS-DISABLED.md).

**16 октября — траектория APK81.** Веб/API15ce2b62 установлен на3015/Tuna; APK81 подтверждён package SHA/OTA на четырёх online устройствах,17 offline исключены. PH011: запись, одна нода и native replay 62 точек по14.732/13.297с, удержание/возврат и отмена с возвратом manual READY; два direct media peers сохранены. Полная точность серии жестов и production SLA открыты. [Поставка и границы](../audits/2026-10-16/POINTER-PATH81-DELIVERY.md).

**Предыдущая поставка 16 октября — общий ввод сценария и зрителей.** Веб ed220169 установлен на3015/Tuna; APK80 подтверждён package SHA/OTA на четырёх online устройствах,17 offline не обновлены. На PH011 прошли запуск с двумя клиентами, отмена, удерживаемое касание и третий зритель; direct media peers сохранены, ручной READY вернулся автоматически. 2546 frontend tests; по1231 Android test в dev/enterprise. Полная запись траекторий, rich evidence и общая production-приёмка открыты. API27 сохранён. [Поставка и границы](../audits/2026-10-16/AUTOMATION-INPUT80-DELIVERY.md).

**16 октября — запись, handoff и видеостена.** UI f7b6f6c1 установлен на3015/Tuna;2529 локальных frontend tests. На PH011 записаны прямой свайп/клик; после пропуска кривого жеста запись продолжается, задача Home завершена без смены media peer. Кнопки закреплены, пустые слоты/меню миниатюр убраны. Конфликт другого управляющего клиента (`device_input_busy`), первый ICE timeout PH025, полные траектории и лёгкие превью остаются открытыми. API27/APK79 сохранены. [Поставка и границы](../audits/2026-10-16/STUDIO-RECORDING-HANDOFF-DELIVERY.md).

**16 октября — восстановление без лишнего viewer reconnect.** UI3a036170 установлен на3015/Tuna; API27/APK79 сохранены. Потеря только idle ACK перед закрытием SCTP теперь допускает первый новый direct peer с собственным native READY; UNKNOWN очистки и неопределённые действия сохраняют строгую блокировку. 2523 локальных frontend tests; контролируемое восстановление на обоих адресах (1.734 с (3015), 2.401 с (Tuna)), два клиента Tuna подтвердили касания и навигацию. PH030 post-OTA delay остаётся отдельной открытой проверкой. [Поставка и границы](../audits/2026-10-16/IDLE-PEER-REJOIN-DELIVERY.md).

**Предыдущая поставка APK79 — обход нативного SIGABRT.** 4 completed OTA, 4 проверенных package SHA, 0 частичных package-проверок, 17 offline. Два клиента PH011 прошли direct касания/навигацию на3015/Tuna и пятиминутный Tuna soak; процесс APK сохранился, основной peer не пересоздавался. UI982/API27 сохранены. PH030 вернулся к READY в новом viewer-сеансе после задержки; быстрое автоматическое восстановление ещё не принято. Причина SDK clock regression и общая production-приёмка остаются открытыми. [Поставка и границы](../audits/2026-10-16/NATIVE-HEADROOM79-DELIVERY.md).

**Предыдущая поставка веба — согласован запуск управления.** UI `982b2240` установлен на 3015/Tuna; API27/APK78 сохранены. Startup ждёт до8с с keepalive500мс; после READY прежние250мс и строгие сроки команд. Полный локальный frontend CI:2511 tests, Linux image:26 страниц/72 assets, без hosted Actions и Docker archives. Два клиента прошли локально, поздний READY — на обоих адресах. Tuna two-client soak выявил native SIGABRT APK78; APK79 только собирается. Причина холодной задержки root, полный игровой исполнитель и общий production SLA остаются открытыми. [Поставка и границы](../audits/2026-10-16/INPUT-STARTUP-WEB-DELIVERY.md).

**Предыдущий срез APK78 — исправлена постоянная блокировка PH030.** APK `1.2.78-dev /10278` установлен на четырёх online устройствах; три package SHA проверены, PH030 — completed OTA/версия и native READY, хеш отдельно не прочитан. PH030: 140 с прямых video/control без новых восстановлений, около 56 FPS, RTT сети 1–10 мс. Два клиента PH011 подтвердили касания и системные кнопки. 17 offline не обновлены. Первоначальная задержка root READY и короткий browser startup timeout остаются в разборе. [Исправление, проверки и границы](../audits/2026-10-16/PH030-STARTUP78-RECOVERY.md).

**Предыдущая поставка 16 октября — транспортный этап.** API `27f3a61f` работает на 3015 и Tuna; веб `19c4272b` сохранён. APK `1.2.77-dev /10277` завершил OTA на PH010/PH011/PH025/PH030: три installed SHA проверены, PH030 — completed команда/версия с занятым чтением хеша. 17 offline не обновлены. На каждом адресе два браузерных клиента подтвердили прямые касания, системные кнопки и сохранение второго участника. Headless0.2 на основном API:885decoded/75RGB за15,016с и два перекрывающихся клиента, server→headless video0байт с запуска. Локальный backend CI:4157passed/11skipped; Android dev/enterprise:по1212tests/3skips. Модель не скачана и не запущена; игровые профили, LAN proof, GPU и общий production SLA остаются открытыми. [Поставка и точные границы](../audits/2026-10-16/MOTOR-TRANSPORT-DELIVERY.md).

Датированные записи ниже описывают предыдущие срезы и не заменяют текущую поставку.

**16 октября — второй транспортный этап AI: capture-only без начальной серверной копии клиенту.**
Реализованы отдельная read-only presence, native source readiness и ограниченная аренда без перехода на relay.
PH011 через временный API-кандидат:15,007с,873decoded,75RGB/4,998Гц,READY/49idle ALIVE/CLOSED,
server→headless media0байт с запуска. Кандидат удалён; основная UI19c4272b/API969a7444/APK76 сохранена.
SDP guard добавлен в backend/Android source; Android compiled/unit-проверен, новый APK не установлен.
Следующий шаг — локальная упаковка и rollout. Модель/игровые действия не реализованы.
[Результаты и границы](../audits/2026-10-16/MOTOR-CAPTURE-ONLY.md).

**16 октября — выполнена первая часть P0-C/G02 AI-плана.** Добавлен headless `motor_worker` с direct H.264,
одним latest-frame slot, RGB sampling и отдельным control admission/idle heartbeat/close.
PH011: 15,013с, 75 RGB, 49 ALIVE, после handover0 server-media bytes; два пересекающихся клиента тоже прошли.
В ходе разработки обнаружен native SDP abort; совместимость клиента исправлена, общая APK hardening не принята.
Модель, profile/multi-touch, DAG delegation и gameplay пока не реализованы. [Квитанция и оставшиеся работы](../audits/2026-10-16/HEADLESS-MOTOR-WORKER.md).

**16 октября — объединён проект будущего игрового AI.** [Основной документ](../design/MOTOR-AI-PLATFORM.md)
содержит 26 требований, сравнение моторных моделей/VLM и доказательств, контракты и план до приёмки.
По коду выявлен будущий конфликт: DAG удерживает discrete reservation и не допустит continuous motor child
без atomic delegation. 5 Гц остаются проверяемой гипотезой для игры, 50 устройств — неизмеренной целью.
Модели не устанавливались; runtime не менялся. [Источники и хеши](../audits/2026-10-16/MOTOR-AI-SOURCE-REVIEW.json).

**16 октября — уточнены Black Russia, зоны управления и 50×4–5 Hz.** Подготовлен проект общего WASD/model профиля с исполнением на APK. Проверено: Android KeyEvent не задействует Windows mapper LDPlayer; NitroGen использует stochastic sampling, а нынешний общий encoder не даёт независимого AI low-FPS stream. Добавлен офлайн motor budget calculator, 9 его тестов прошли. Это подготовка: профили/multi-touch/GPU worker/gameplay ещё не реализованы; runtime сохранён. [Навигация и нагрузка](../audits/2026-10-16/NITROGEN-NAVIGATION-AND-BUDGET.md), [дизайн](../design/GAME-CONTROL-PROFILES.md).

**16 октября — готовность NitroGen проверена по коду и первоисточникам.** Сценарий: отдельная GPU-станция получает кадры APK и возвращает действия по LAN. Основа стрима есть, но headless client, игровой gamepad/multi-touch adapter и observation/action lifecycle ещё нужны; дефекты цвета/восстановления остаются. Ревизии, фактические 25 измерений действий, обсуждения, аппаратный срез и критерии первого supervised episode зафиксированы. Модель не установлена, GPU/gameplay не испытаны; текущий runtime сохранён. [Аудит](../audits/2026-10-16/NITROGEN-READINESS.md).

**16 октября — каналы Studio и резервный ввод исправлены.** На 3015 и Tuna установлен UI `19c4272b`: временные режимы сохраняют согласованные каналы, фоновые ICE-попытки не блокируют admission резервного управления. Проверен настоящий native READY и DOWN/UP при задержанном ответе fallback. Локально и в точном frontend CI: 172 набора / 2508 тестов. Сетевые потери PH030, прежние heartbeat-сбои и искажение цвета остаются открытыми; API969/APK76 сохранены. [Результаты и ограничения](../audits/2026-10-16/MODE-TRANSPORT-AUTHORIZATION.md).

**15 октября — новый парк и оформление установлены на 3015 и Tuna.** AG Grid Community: resize/reorder/pinning, сохранение вида; телефон — карточки. Шесть палитр, независимые акцент/плотность/шрифт, auto/pin sidebar, optional glass и логотип. Локально 169 suites / 2455 tests; exact-source CI и конечные браузерные проверки прошли. API969/APK76 сохранены, APK77 не устанавливался; heartbeat на паузе. [Поставка и оставшиеся пункты](../audits/2026-10-15/UI-REFINEMENT-DELIVERY.md).


**15 октября — новый визуальный аудит и проектирование.** Сняты 127 состояний и 2468 видимых кнопок/ссылок; учтены 29 шаблонов страниц и 47 DialogContent. Подтверждены ошибки акцента/плотности, контраста и мобильного toolbar; составлены 20 пунктов доработки, sidebar/theme/glass и контракт Android-файлового менеджера. Условные окна и роли имеют явные пробелы покрытия. Рабочий транспорт не менялся; новые функции не установлены. [Аудит и этапы](../audits/2026-10-15/UI-UX-VISUAL-AUDIT.md).

**15 октября — этап зафиксирован, доработка приостановлена по просьбе пользователя.** Удалённая PH025 прошла пользовательскую проверку: видео и управление напрямую, RTT около 20 мс; история подтверждает сеть 22 мс и ACK 25–26 мс. Рабочим остаётся APK 76, подготовка 77 не установлена. Heartbeat `enterprise` приостановлен. [Зафиксированное состояние и следующий этап](../audits/2026-10-15/STREAM-CONTROL-FREEZE.md).

**15 октября — установка APK 76 и проверка прямого управления.** Все 15 доступных эмуляторов завершили OTA: 14 подтвердили хеш установленного пакета, PH030 — команду и версию. Шесть выключенных устройств ожидают. На текущем вебе прошли два одновременных клиента, десять клиентов через Tuna, 40 системных нажатий, фактический ввод Unicode в fullscreen и три восстановления RTC. Отдельно проверено восстановление после перезапуска процесса APK. Сетевые отказы прежних прогонов сохранены; непрерывность без signaling и общий production-статус остаются открытыми. [Установка и границы](../audits/2026-10-15/DIRECT-KEYBOARD76-DELIVERY.md)

**Предыдущее наблюдение 15 октября — клавиатура76 и незакрытый совместный сеанс.** НаPH011 APK76 подтверждён по файлу и OTA;PH030 сообщает76 с completed OTA,13 доступных машин остаются72,шесть офлайн. Два локальных клиента и фактический Unicode/IME/fullscreen прошли проверку. Текущий прогон десяти клиентов черезTuna потерял готовые peer при открытии остальных; массовая OTA удержана. Исправление transient auth и диагностика signaling подготовлены,ещё не установлены. [Факты и границы](../audits/2026-10-14/KEYBOARD76-PARTIAL-DELIVERY.md).

**Предыдущее наблюдение 14 октября — прямые системные кнопки и восстановление ввода.** APK `1.2.72-dev /10272`, UI37543bb2 и APIbe0578d0 установлены; 15 доступных эмуляторов завершили OTA, 14 подтвердили установленный SHA, 1 — только команду и версию; шесть офлайн ожидают. На обоих адресах прошли два клиента с mouse/touch и кнопками; десять клиентов через Tuna подтвердили 40 системных нажатий и совместные жесты. Автовосстановление после трёх принудительных обрывов RTC проверено. Реальное скрытие вкладки, телефон/hotspot, 20+, полноценные клавиатура/IME, звук, автономность без сервера и полный перенос CI остаются открытыми. [Результаты и границы](../audits/2026-10-14/DIRECT-SYSTEM-INPUT72-DELIVERY.md).

**Предыдущее наблюдение 14 октября — совместный ввод и fullscreen.** UI `103d8532` / API `3538b650` установлены на 3015 и Tuna. APK `1.2.69-dev /10269`: завершённая OTA и версия подтверждены на 15 доступных эмуляторах; на 14 проверен установленный SHA, у PH030 чтение хеша удержано активным вводом. Шесть офлайн остаются без нового grant. Десять независимых клиентов прошли прямые жесты, takeover и закрытие одного без обрыва девяти; fullscreen и сенсорная геометрия 390×844 /844×390 проверены на обоих адресах с сохранением одного peer. Полноценная клавиатура/IME, прямые системные кнопки, 20+, реальный телефон/hotspot, автономность без сервера и полный перенос CI остаются открытыми. [Установка и границы](../audits/2026-10-14/SHARED-INPUT-FULLSCREEN-DELIVERY.md).

**Историческое наблюдение 13 октября — качество и доставка.** UI `a3e61800` / API `69da45cb` установлены на 3015 и Tuna. APK `1.2.68-dev` (10268) подтверждён установленным SHA и завершённой OTA-командой на 14 доступных эмуляторах; семь офлайн, включая PH030, не обновлены. PH010 в обычном Chrome на обоих адресах получил 54–59 FPS при цели 60 и все 13 native подтверждений жеста; после перехода на прямой поток резервное серверное видео не передавалось. Настройки качества применяются вживую; краткая строка показывает маршрут, RTT, размер, фактические FPS и битрейт. Добавлены счётчики вкладок и потоков; скачивание последнего APK проверено побайтово. Совместный ввод, автономный peer без сервера, прямые системные кнопки, реальный телефон, широкая WAN/TURN matrix и полный перенос CI остаются открытыми. [Установка, проверки и границы](../audits/2026-10-13/DIRECT-SOURCE-QUALITY-DELIVERY.md).

**Ранее 13 октября — подтверждён прямой маршрут с ноутбука.** UI `954d466c` установлен на 3015 и Tuna. PH025 передаёт видео и ввод напрямую по NAT/UDP: RTT сети 20–22 мс. На PH030 наблюдалось около 30 минут прямого видео и готового ввода без восстановления в счётчиках; следующий viewer учтён отдельно. Исправлен поздний отказ запуска, который мог блокировать ввод при живом видео; проверены реальные жесты и шесть повторных открытий. Диагностика причин завершения адаптирована для телефона. APK `1.2.65-dev` был установлен на момент этой проверки; точный установленный SHA подтверждён на всех 15 доступных эмуляторах, включая PH030; шесть офлайн не обновлялись. [Изменения, границы и результаты](../audits/2026-10-13/DIRECT-INPUT-RECOVERY.md) · [Протокол](../audits/2026-10-13/DIRECT-INPUT-RECOVERY-OBSERVATION.json).

**Предыдущее наблюдение 13 октября, 06:35 UTC — прямая связь и диагностика.** UI `73419abe` / API `b65b0b54` обслуживают 3015 и Tuna. APK `1.2.65-dev / 10265` подтверждён установленным SHA на 14 доступных эмуляторах. PH030 ранее завершил OTA65, но сейчас офлайн; актуальный SHA и стабильность ноутбучного ввода не приняты. PH010 подтвердил прямое видео и native жест на обоих адресах. Исправлены поздний диагностический echo и гонка повторного допуска до точного RELEASE. Причина завершения нативного ввода теперь сохраняется отдельно от результата cleanup. Общий ввод, Home/Back напрямую, независимость от серверного lease, WAN/TURN и длительная стабильность остаются открытыми. [Изменения и проверки](../audits/2026-10-13/DIRECT-SESSION-STABILITY.md) · [Протокол](../audits/2026-10-13/DIRECT-SESSION-STABILITY-OBSERVATION.json) · [Локальные тесты и границы переноса CI](../audits/2026-10-13/CI-COST-AND-LOCAL-RUNNER.md).

**Предыдущее наблюдение 12 октября, 22:04 UTC — отмена открытия управления.** UI `3d5c2a8f` / API `fc273fa3` обслуживают 3015 и Tuna. Исправлены отменённый OPEN, поздняя ошибка CLOSE, потеря позднего RELEASE и блокировка CLOSE собственной диагностикой; сервер подтверждает только положительно доказанную отмену до доставки в APK. PH010 прошёл конечные проверки прямого видео и нативного жеста на обоих адресах; это не приёмка пользовательского PH030. APK63 подтверждён по установленному SHA на PH010/PH030, массовый rollout удержан. Старый сеанс PH030 с прямым видео без ввода сохранён; новая проверка ноутбука, native authorization/cleanup, общий ввод, WAN и soak остаются открытыми. [Исправление и границы](../audits/2026-10-13/INPUT-OPEN-CANCELLATION.md) · [Протокол](../audits/2026-10-13/INPUT-OPEN-CANCELLATION-OBSERVATION.json) · [Путь и видеобуфер](../audits/2026-10-12/LOCAL-HOST-ROUTE.md) · [Общий ввод: проект](../audits/2026-10-12/SHARED-INPUT-CONTRACT.md).

**Предыдущее наблюдение 12 октября, 12:36 UTC — APK и вход.** UI/API `ed9d54d0` обслуживают 3015 и Tuna. В «Обновлениях» можно скачать последний APK выбранного канала с прогрессом и отменой; рядом официальный LDPlayer. Полный APK60 совпал по SHA-256 на обоих адресах (927/8489 мс в конечной проверке). Вход тёмный и адаптивный; сохранённая светлая тема рабочего пространства не сбрасывается. Свежий срез: 14 онлайн сообщают APK10260, семь офлайн; ранее installed SHA подтверждён на 15 устройствах. После установки PH010 подтвердил прямые видео и DOWN/MOVE/UP через оба адреса. 3762 backend tests / 361 subtests и 2260 frontend tests прошли. [Изменения и границы](../audits/2026-10-12/APK-DOWNLOAD-AND-LOGIN.md) · [Протокол](../audits/2026-10-12/APK-DOWNLOAD-AND-LOGIN-OBSERVATION.json).

**12 октября, 02:29 UTC — предыдущая конечная проверка транспорта.** UI `331bac0a` / API `98370d43` были установлены на 3015 и Tuna. Исправление ввода изменило только фронтенд; код бэкенда в этих ревизиях одинаков. На обоих адресах совпадают 29 JS/CSS, PostgreSQL и Redis готовы, история сеансов требует авторизации и отдаётся с private/no-store. APK `1.2.60-dev / 10260` подтверждён установленным SHA и завершённой OTA на 15 доступных устройствах. Шесть выключенных устройств не подтверждены; обычный канал Android не изменён.

На PH010 обычный Chrome 154 получил прямое видео и подтверждения Android для DOWN/MOVE/UP. На каждом адресе проверены по три обрыва RTC, фактическое резервное видео и автоматический возврат прямого ввода. При прямом просмотре серверная копия не дала новых байтов; отдельный серверный зритель продолжил получать кадры. Смена маршрута ввода больше не ждёт опустошения очереди idle heartbeat.

Полная задержка картинки, ближайший путь во всех сетях, обнаружение при удалённом VPS, физическая смена сети, совместный ввод, звук, клавиатура и 60 FPS остаются открытыми. [Протокол предыдущего испытания](../audits/2026-10-12/DIRECT-VIDEO-HANDOVER-OBSERVATION.json), [изменения и границы проверки](../audits/2026-10-12/DIRECT-VIDEO-HANDOVER.md). Удалённая PH025 пока получает серверное видео: Android answer пришёл, ICE-ответов нет; [сетевой отказ](../audits/2026-10-12/PH025-DIRECT-ROUTE-OBSERVATION.json).

**12 октября — сборщик диска возобновлён, непрерывность не подтверждена.** Предыдущий worker завершился: последний срез20:53UTC,89 записей. Новый процесс с21:33UTC проверен по identity и свежим срезам; интервал120с,24 именованных файла, Docker каждые8срезов, лимит16MiB/24ч. Пропуск наблюдений сохранён; причина остановки и роста диска неизвестна. Lifetime, автозапуск и VSS не гарантированы. [Срез возобновления](../audits/2026-10-12/STORAGE-WATCH-RESUMED.json).

**Ниже — датированные предыдущие этапы, не новая приёмка.**

**11 октября, после перезагрузки — новые API/UI и APK55 установлены.**
15 доступных эмуляторов подтвердили installed SHA APK1.2.55-dev/10255 и completed OTA;
6 offline записей не обновлены и не имеют queued grant. Проверены оба origin,
совпадение29 stream-route JS/CSS и текущего HTTP OpenAPI. PH010/PH011 через3015 и
PH025 черезTuna показали живой server fallback и непрерывный обратный жест.
Прямой ICE в новых тестах не установился. При массовой загрузке OTA были idle
receipt timeout с автоматическим восстановлением; direct/latency/soak остаются OPEN.
После CHKDSK C: Healthy/OK;10 Git objects восстановлены, fsck0. Новый collector
limited, без гарантии lifetime/VSS/autostart. Причина потери места не установлена.
[Установка, автообновление и открытые дефекты](../audits/2026-10-11/POSTBOOT-IDLE55-DELIVERY.md).

Следующие записи описывают прежние срезы; их запреты установки и версии относятся
к указанному времени, а не к текущей установленной версии.

**11 октября — подготовлены исправления неподвижного экрана и восстановления отрисовки.**
Source `52239980`: все три CI прошли. Android проверен в четырёх обычных вариантах
и совместном профиле WebRTC + planar input + continuous input; веб — 2226 тестов,
26 собранных страниц и73 client assets; backend JUnit —4028 записей/43 skips без
ошибок. Добавлены ограниченный raw refresh раз в секунду, watchdog реальной
presentation и четыре native freshness measurements в прежние последние10 сеансов.
Подписанный стендовый APK55 и новые API/UI ещё не установлены: C: Full Repair Needed;
пользователь выбрал перезагрузку позже. CI APK подписан временным ключом и не годится
для обновления pilot package. [Изменения, CI и порядок установки](../audits/2026-10-11/STREAM-IDLE-PROGRESS-RECOVERY.md).

**11 октября,16:26 UTC — новый readback:15 APK54 подтверждены.** PH030 завершил
ранее выданный OTA grant; проверен установленный SHA. Вместе14 completed OTA и
PH010 already-target. Шесть offline машин не получили команду, queued grant нет.
API/UI обоих адресов остаются6ee; новая версия55 не устанавливалась.
[Неизменяемый follow-up](../audits/2026-10-11/APK54-FLEET-FOLLOWUP.json).

**11 октября, 15:28 UTC — готовый APK54 распространён на весь доступный парк.**
У всех 14 работающих эмуляторов проверен SHA APK 1.2.54-dev/10254: 13 адресных OTA
завершены, PH010 уже имел эту версию. Семь устройств вне сети: PH030 ожидает
подключения по grant до 16:22 UTC/21:22 UTC+5, остальные 6 пока не получили команду.
Использован ранее опубликованный APK; новой сборки, очистки данных и замены API/UI
не было. Recovery500 прошёл API/UI CI76 с идентичными деревьями исходников; установка
по-прежнему ждёт ремонта C:. [Доставка и точные границы](../audits/2026-10-11/APK54-FLEET-DELIVERY.md).

**11 октября,14:46 UTC — продолжено восстановление прямого канала.** Source
`500186e2` завершает exact peer при потере control DataChannel и автоматически
согласует следующий; старые касания не повторяются. Исправлены terminal reject
для временного auth failure, bounded capability retries и backoff после здорового
видео.690 WS tests/44 subtests,192 frontend tests, types/lint/schema прошли.
CI запущен, новая установка не выполнена: C: всё ещё Full Repair Needed.
Оба адреса подтвердили6ee; API сообщает PH01054/PH01153/PH02552. Эти reported
versions не заменяют installed SHA или runtime acceptance. [Изменения и допуск](../audits/2026-10-11/DIRECT-CHANNEL-RECOVERY.md).

**11 октября — подтверждено повторное повреждение C: и Git; обновление ожидает ремонта.**
Elevated scan завершён: `ScanErrorsFoundNeedSpotFix`; current preflight всё ещё
`Full Repair Needed`. Git fsck нашёл10 corrupt objects, четыре относятся к current
source. Pushed source3089 files проверен независимо по Git blob hashes; consistent
PostgreSQL dump полностью прочитан. Локальная копия на том же SSD, без полного
backup личных данных. CHKDSK C: `/f` подтверждён на следующую загрузку; reboot,
rollback и repair этой работой не выполнены.

Установщик допускает новый strict telemetry DTO;61 tests/69 subtests прошли.
VSS provider изолирован от RAM/process collector,41 host tests прошли. Старый
worker остановился после11:35 UTC; новый elevated13708 начал24h окно12:24 UTC.
Exact VSS max снова около19.057GiB вместо8GiB, причина смены лимита UNKNOWN.
UI/API остаются6ee, fleet смешанный, APK55 не собран/подписан/выложен.
[Квитанция и следующий порядок](../audits/2026-10-11/HOST-REPAIR-1216.md).

**11 октября — кандидат APK55 прошёл CI, установка ещё не выполнена.** Автоматические native ICE/stage
reports привязаны к истории просмотра; initial/sparse/terminal сбор ограничен
общим10-session/32KiB journal. Frontend153 suites/2208 tests, backend3638 tests
и320 subtests, Android build/profiles прошли. Pilot signing, адресная OTA и
native runtime acceptance ещё не выполнены. Новый source не установлен
ни на3015, ни на туннель, ни на весь парк эмуляторов.
[Протокол, лимиты и проверки](../audits/2026-10-11/NATIVE-DIRECT-DIAGNOSTICS-SOURCE.md).

**11 октября,11:27 UTC — C: продолжает уменьшаться при постоянном VHDX.**
За237 срезов03:35→11:27 UTC свободное место снизилось на1 647 091 712B
(~1.53GiB); Docker VHDX allocation во всех срезах236 073 254 912B без роста.
Шесть заданных LDPlayer files и pagefile CIM allocation также постоянны.
Это не доказывает отсутствие записей внутри Docker или конкретного writer:
VSS/USN/kernel недоступны. Collector43984 продолжает24h окно, не заменялся.
[Неизменяемый промежуточный срез](../audits/2026-10-11/STORAGE-OBSERVATION-1127.json).

**11 октября — действующий срез.** UI/API `6ee80c1f` обслуживают 3015 и туннель; 29 клиентских assets совпадают. PH010 проверен на APK `1.2.54-dev`, ещё шесть машин — на53, две — на52. Прямые касания подготовлены и прошли CI, но новая установка API/UI остановлена до загрузки образа: Windows сообщает `Full Repair Needed` для C:. В текущем PH010 сеансе работал server fallback, прямой ICE не открылся. [Фактическая установка](../audits/2026-10-11/CURRENT-STREAM-DELIVERY.json) · [Подготовленная доставка и ограничения](../audits/2026-10-11/DIRECT-INPUT-DELIVERY-BLOCKED.md).

**Наблюдение диска возобновлено11октября,03:35 UTC на24 часа.** Окно18:22→02:22 UTC
завершилось:241 замер,−2.25GiB свободного места, Docker VHDX allocation+1.25GiB.
Новый limited worker PID43984 подтверждён срезом и process epoch; срок12октября
03:35 UTC,721×120s/16MiB. Разрыв02:22→03:35 UTC не покрыт. VSS/kernel writer
и причина всего расхода C: неизвестны; `Full Repair Needed` сохраняется.
[Текущий статус и ограничения](HOST-RESOURCES.md).

**10 октября, 16:17UTC — автоматическое восстановление допуска управления установлено.** Занятая вкладка и временный отказ сервера повторно согласуются без повтора касаний. [Доставка и пределы проверки](../audits/2026-10-10/CONTROL-ADMISSION-RECOVERY-INSTALLED.md).

**Предыдущий этап:** конечный read-only тест PH030 на 10251 получил 223 кадра WebRTC. Этот исторический результат не является текущей версией APK, прямым вводом или доказательством loopback. Текущая установка описана выше.

**Предыдущий результат пользователя: прямой канал с ноутбука — 20/20 ответов,
p95 25,8 мс, NAT/UDP.** Браузер и PH030 на одном ноутбуке без VPN. Это конечная
проверка echo, видео/управление остаются WebSocket через сервер; localhost и
задержка картинки не доказаны. Точное время теста не указано.
[Результат и границы](../audits/2026-10-10/PH030-LAPTOP-CHANNEL-USER-OBSERVATION.md).

**Отдельное предыдущее наблюдение основного ПК, 10 октября, 10:20 UTC:** ответ PH030 на согласование есть,
прямой канал из браузера основного ПК не открылся. Позднейший конечный
RTP-тест ноутбука описан в новом receipt; nearest-path и основной транспорт ещё открыты. Limited storage observer возобновлён после неожиданной остановки;
разрыв покрытия сохранён.
[Тест и восстановление наблюдения](../audits/2026-10-10/PH030-DIRECT-PATH-FOLLOWUP.md).

**10 октября, 06:36UTC — UI/API c17332eb установлены.**
PH030-only admission panel доступна на3015 и публичном адресе. Anonymous401,
private/no-store, два профиля, лимиты30s/20samples и отсутствие допуска PH011
подтверждены. Визуально проверена панель; peer не запускался. APKPH0301.2.50-dev
подтверждён отдельным OTA receipt. Direct channel/media/input/latency ещё OPEN.
[Установка, проверки и границы](../audits/2026-10-10/DIRECT-ADMISSION-INSTALLED.md).

**10 октября, 05:53 UTC — PH030 адресно обновлён штатным OTA.**
На ноутбуке без VPN установлен diagnostic APK **1.2.50-dev / 10250** (`e54b2fc8`).
Один command ID, completed receipt после перезапуска и фактический APK SHA совпали.
Package data и ID сохранены; ordinary Android channel не изменён. Это echo-only
модуль, не прямой stream/input. TURN REST/TLS fixtures прошли конечные проверки;
обычная панель per-device admission подготовлена и проверена локально, ещё не
установлена. Browser-on-laptop channel и production media/control остаются OPEN.
[OTA, сеть, source и пределы](../audits/2026-10-10/DIRECT-PROBE-TURN-AND-LAPTOP.md).

**10 октября, 04:16UTC — native setup проверен, UDP-путь локализован до обмена между peers.**
Exact161 прошёл4CI/signed admission. Три native process окна: answer392/226/243мс,
по13reports; канал не открылся. Финальный APK-owned capture:237исходящих к browser
candidate/0обратных, STUN1/1,239packets/0kernel drops. Место потери/NAT/VPN/firewall
UNKNOWN. Original APK восстановлен, probeoff/allowlist[], ordinary local11/public2
frames без decode/render errors. UI639/API369 сохранены, API epoch04:12:56UTC.
Public opening server_rejected сохранён; control/latency и stable1.3 не приняты.
Product9/41,legacy7. [Новое измерение и возврат](../audits/2026-10-10/DIRECT-PROBE-NATIVE-PROGRESS-CANARY.md).

**Предыдущий срез10октября — public-STUN canary934; ответ APK не получен.**
Exact934 прошёл четыре CI и signed admission. Один PH011: browser host1+srflx1,
offer→close7,989s, answer0,echo0/RTTunknown. JNI/factory присутствуют; конкретный
native setup этап пока UNKNOWN. Выявлен пробел: stats начинались только после
answer. Фиксированы bounded native этапы/pre-answer stats, local tests/lint passed;
на момент этого среза новый source ещё не был установлен. Исходный APK восстановлен, gateoff/allowlist[],
UI639/API369 сохранены, API container epoch обновлён. Обычный public25/local24
view-only frames без decode/render errors проверен после возврата. Product9/41,
direct/latency и stable APK NO-GO сохраняются.
[Реальное измерение и возврат](../audits/2026-10-10/DIRECT-PROBE-PUBLIC-STUN-CANARY.md) ·
[Source диагностики следующего этапа](../audits/2026-10-10/DIRECT-PROBE-NATIVE-PROGRESS-SOURCE.md).

**10 октября — UI автоматического управления установлен и проверен в конечном scope.**
UI639/API369,1996frontend tests/types/scoped lint. Повторный idle recovery, точный
RELEASE/fresh-viewer gate и гонки навигации/capture исправлены. На UI13 и финальном639
по одному натуральному unknown-pointer notice сменились новой готовностью и
подтверждённым Home. Перестановки RELEASE/hold/terminal покрыты fixtures;
native latency/direct/fleet OPEN.
[Установка, реальные срезы и границы](../audits/2026-10-10/CONTINUOUS-AUTO-RECOVERY-INSTALLED.md).

**10 октября — native ICE counters проверены на реальном APK.**
Исправленный8447 прошёл все4 exact-source CI и signed admission. Один PH011:
12native reports, remote candidates0/pairs0/DTLSnew; packet counters unknown.
Browser177checks/0responses, channel/RTT нет. Это различимый результат,
не доказанная mDNS/VPN причина. Исходный APK восстановлен, probeoff/allowlist[],
временные3016/3017 и вкладки закрыты. Обычный public viewer вернул662decoded/drawn
frames без invalid/decode/render errors. В том canary UI/API369 сохранены; direct/latency OPEN.
[Native/browser counters, маршруты и возврат](../audits/2026-10-10/DIRECT-PROBE-NATIVE-COUNTERS-CANARY.md).

**Предыдущий срез 10 октября — browser ICE без native counters.** Один диагностический canary:
APK answer получен, две пары проверяются,177 requests/0 responses,0 echo/RTT.
Источник отказа сужен до установки сетевого пути; конкретная причина ещё UNKNOWN.
Исходный APK восстановлен, API probe выключен, временные3016/3017 остановлены.
Обычный публичный viewer после cleanup дал9 decoded/drawn frames без ошибок.
Панель network snapshot выключена compile-time в стандартном UI369; реальный
срез снят только во временном loopback diagnostic UI. Это уточняет прежнюю
формулировку доставки source, не подтверждает direct media/control или SLA.
[Измерение, установка и следующий шаг](../audits/2026-10-10/DIRECT-PROBE-NETWORK-CANARY.md).

**Предыдущая установка10октября — broadcast.** В том срезе на обоих адресах UI/API369;
все4 exact-source CI success:3428 backend tests/252subtests,1966 frontend tests.
Изолированный PostgreSQL/Redis test подтвердил202, commit и admission. На рабочем
стенде ожидаемый404 после чтения presence проверен без запуска массовых действий.
APK, schema/OTA и45соседних контейнеров сохранены при каждой установке.
Idle control и direct transport остаются открытыми; probe выключен.
[Установка, проверки и остаток](../audits/2026-10-10/BROADCAST-INSTALLED-ACCEPTANCE.md).

Исходные CI registry failures устранены: gateway и Redis pressure helpers прошли
полный прогон на pinned official mirror. Старые отрицательные receipts сохраняются.
Последовательный ACK244local/487public и idle512fault записаны отдельно:
[измерение без касаний](../audits/2026-10-10/IDLE-LOCAL-PUBLIC-COMPARISON.md).

**APK1.3.0 — проверен текущий контракт и составлен release plan.** Development
версия 1.2.52-dev/10252 установлена на 15 устройствах с проверенным SHA; шесть offline-устройств не объявлены обновлёнными. PH030 выключен после установки. Private continuous/direct flags не являются stable release профилем.
Новое capability negotiation, native resource gates, idle reliability и signing
promotion требуют отдельной приёмки. [Матрица и критерии](../design/APK-1.3-COMPATIBILITY-AND-RELEASE.md).

**10 октября — сборщик диска возобновлён после обнаруженной остановки.**
86samples21:09→23:59UTC: C:−6,075GiB, Docker VHDX allocation постоянен.
Процесс отсутствовал при running status; причина остановки/расхода UNKNOWN.
Новый PID/epoch/complete samples сверены, окно00:14→12:34UTC,371×120s/16MiB.
Разрыв не покрыт, VSS/USN/kernel writer attribution недоступны.
[Receipt и границы](../audits/2026-10-10/STORAGE-OBSERVER-RESUME.md).

**Исторический срез9октября: выполнены две попытки native direct pilot.** JNI и авторизованный
SDP answer подтверждены, DataChannel не открылся, RTT не измерен. API9ad установлен,
прежний APK PH011 восстановлен, эксперимент отключён с пустым allowlist;
UI d70/45соседних контейнеров/schema/OTA сохранены. Idle failure снова воспроизведён.
Source close-race/фазы диагностики исправлены:81backend,63delivery,8frontend tests,
Ruff/mypy/types прошли; exact369 CI и установка этих исправлений теперь приняты; native connectivity ещё нет.
Product9/41,legacy7 сохраняются. [Пилот и следующий gate](../audits/2026-10-09/DIRECT-PROBE-PILOT.md).

**Последующий source этап:** добавлен bounded browser ICE/DTLS snapshot при отказе:
один getStats in flight,32вызова максимум, unknown counters и возраст среза видны,
адреса/ключи не сохраняются.16focused frontend tests/types passed; source входит в369,
но стандартный UI build flag выключен. Новый native canary выполнен во временном
диагностическом UI; результат выше. [Source scope](../audits/2026-10-09/DIRECT-PROBE-NETWORK-SNAPSHOT.md).

**Первый source этап9октября: разрешён и написан direct RTT canary.** Браузерный WebRTC,
серверное межпроцессное согласование и отдельный Android debug source set готовы
для испытания. По умолчанию отключён; Android JNI не входит в обычные сборки.
Видео/касания на рабочей установке остаются WS; живой direct RTT ещё не измерен.
[Scope, проверки и rollout gates](../audits/2026-10-09/DIRECT-PROBE-SOURCE.md).
Последующая source коррекция изолирует BrokenPipe/slow viewer от общего listener;
78 backend regression tests прошли. [Доказательство](../audits/2026-10-09/DIRECT-PROBE-VIEWER-ISOLATION.md).

**9 октября: UI d70f55c6 установлен на 3015 и выбранном публичном адресе.**
Повторная idle-потеря ACK отличается от неизвестного результата касания; held/terminal
unknown, остановка input и прежние deadlines сохранены. Исправлен контраст статуса
в светлой теме. 1950 frontend tests / 139 suites, types/build прошли.
Конечная браузерная проверка приняла только wording/контраст и показ транспорта;
idle timeout повторился, его причина и задержка остаются UNKNOWN/OPEN.
[Установка и проверка](../audits/2026-10-09/IDLE-CONTROL-UX-INSTALLED.md) ·
[Исходное воспроизведение и границы](../audits/2026-10-09/IDLE-CONTROL-RELAY-REVIEW.md) ·
[Исследование прямого транспорта](../design/BROWSER-DIRECT-TRANSPORT.md).

**9 октября: дополнительная проверка туннеля нашла и исправила Grafana.**
На публичном адресе большие JS давали parse errors; на3015 dashboard работал.
Адресный gzip static-assets установлен graceful reload без replacement46контейнеров.
Два повторных открытия дали реальные панели без новых console errors;
22страницы, deep-link/F5, JSON export и ELK worker проверены. PH011 получил6кадров,
но steady FPS/control не приняты. Product9/41 сохранён.
[Доказательства и границы](../audits/2026-10-09/PUBLIC-WEB-SUPPLEMENTAL-QA.md).

**Первоначальная доставка 9 октября, 15:53 UTC:** публичный UI синхронизирован с 3015.
На том срезе Tuna-host показывал UI86354350/API d720232e. Вход, каталог22сценария, builder и мониторинг
проверены; временный monitoring failure сохранён. Все46 контейнеров и API/WS/
bootstrap сохранены, новых images нет. Public stream/control/soak не приняты,
9/41 не меняется. [Receipt](../audits/2026-10-09/PUBLIC-WEB-DELIVERY.md).

Сверено **10 октября 2026 (UTC+5)**. Это действующий указатель статусов; машинный
источник — [STATUS-REGISTRY.json](STATUS-REGISTRY.json). Установка и runtime:
[CURRENT-STATE](CURRENT-STATE.md). Критерии эксплуатации: [READINESS](READINESS.md).
Предыдущая [подробная сверка чата и кода](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md)
сохранена как датированный срез. Она не переписывается при изменении этого списка.

## Что означают числа и насколько велика работа

**9 принято / 41 открыто из 50** — продуктовый план. Принятое означает только
scope доказательств конкретного пункта. В исходном аудите было шесть подтверждённых
дефектов; все шесть имеют записанную приёмку EP-001–006. Остаток включает расширение
возможностей, дизайн и будущие подсистемы. Новые дефекты могут возникать внутри
частично выполненного пункта: пример — clock regression рекордера и idle timeout.

**34 source-fixed / 7 незакрытых из 41** — отдельный старый веб-аудит. Три из семи
PARTIAL, четыре OPEN. Это не дополнительные семь независимых задач поверх 41.
«Два» в предыдущем сообщении означало два коммита, отдельного реестра из двух проблем нет.
Resource/Fleet32 admission имеет отдельные gates и также не складывается с продуктовым счётчиком.

Приоритет P1/P2 сохранён из baseline. Масштаб S/M/L/XL — инженерная оценка оставшегося
охвата, не срок и не severity: S — локальный фикс, M — отдельный workflow,
L — несколько слоёв/проверок, XL — новая подсистема или большой нагрузочный этап.
У принятых строк это оценка исходного объёма, а не оставшаяся работа.

## Сначала закрыть риски эксплуатации

1. **Диск и ОЗУ (EP-033/047):** limited observation возобновлено10Oct00:14UTC
   до12:34UTC:371×120s/16MiB,24namedfiles и RAM/Docker/WSL. Прежний процесс
   отсутствует,86samples закончились9Oct23:59UTC. C:−6,075GiB при постоянном
   Docker VHDX allocation; источник расхода UNKNOWN. Разрыв не покрыт, VSS/USN/
   kernel evidence недоступны; resource soak/retention и RAM acceptance нужны.
   [Окно и границы](../audits/2026-10-10/STORAGE-OBSERVER-RESUME.md).
2. **Управление и native latency (EP-020/029):** UI639/API369 установлен.
   Повторное idle recovery и гонки navigation/capture исправлены; fresh RELEASE/
   frame/STARTUP gates не повторяют неизвестный жест. На PH011 проверены конечные
   UI readiness/navigation/video; по одному UI13/639 unknown-pointer recovery наблюдены,
   перестановки RELEASE/hold/terminal пока fixture-only, wire trace отсутствует.
   ACK пересекает500ms; server timing spans сами по себе не локализуют причину.
   Network/APK/native/reverse-path correlation, latency/fleet/direct gates OPEN.
   [Установка и границы](../audits/2026-10-10/CONTINUOUS-AUTO-RECOVERY-INSTALLED.md).
   [Измерения и следующий шаг](CONTINUOUS-INPUT-TIMINGS.md).
3. **Общий владелец input (EP-017/020):** Redis lease для continuous viewer существует;
   согласование viewer/task/API/scheduler и неизвестных результатов во всех комбинациях не принято.
4. **Rich recorder (EP-018):** clock fix1577e01e сохранён в UI86354350;
   PH011 mixed tap/XPath/tap/Back и перенос в граф приняты в конечном scope.
   Следующий объём — trajectory/context/Unicode/IME; EP-018 остаётся OPEN/PARTIAL.

## Реестр продукта

Baseline [5 октября](../audits/2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json) намеренно
сохраняет первоначальное OPEN. Следующая таблица показывает действующий остаток.
Прогресс PARTIAL не равен ACCEPTED; никакая строка здесь не подтверждает Fleet32/500/1000.

| ID | Приоритет | Масштаб | Статус / прогресс | Работа |
| --- | --- | --- | --- | --- |
| EP-001 | P1 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Сохранять видимость колонок после F5 |
| EP-002 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Исправить canonical export визуального сценария |
| EP-003 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Открывать existing canonical script в builder |
| EP-004 | P1 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Нормализовать device_model в Fleet Matrix |
| EP-005 | P2 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Не показывать пустое количество узлов в pipeline picker |
| EP-006 | P1 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | HTTP rejection не является delivered в legacy webhook |
| EP-007 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Встроенная Grafana должна открыть запрошенный dashboard |
| EP-008 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Подключить реальные HTTP RPS и latency panels |
| EP-009 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | История CPU/RAM с корректным scope |
| EP-010 | P1 | L | OPEN / PARTIAL | Активные tunnels и fleet metric coverage |
| EP-011 | P1 | L | OPEN / PARTIAL | Версионировать все browser table/view preferences |
| EP-012 | P1 | M | OPEN / OPEN | Расширить registry typed columns и пресеты |
| EP-013 | P2 | M | OPEN / PARTIAL | Единые tokens, preferences и icon semantics |
| EP-014 | P1 | L | OPEN / PARTIAL | Studio canonical AST и отдельный layout |
| EP-015 | P1 | L | OPEN / PARTIAL | Studio source schema, drafts, conflict и undo |
| EP-016 | P1 | L | OPEN / PARTIAL | Studio каталог всех runtime actions |
| EP-017 | P1 | M | OPEN / PARTIAL | Live device picker и capability preflight в Studio |
| EP-018 | P1 | L | OPEN / PARTIAL | Запись Android input и selector candidates |
| EP-019 | P1 | L | OPEN / OPEN | Пошаговый trace и replay с frame correlation |
| EP-020 | P1 | L | OPEN / PARTIAL | Server/agent debug pause, step, cancel и safety |
| EP-021 | P1 | XL | OPEN / OPEN | Объединить automation workspace и references |
| EP-022 | P1 | M | OPEN / PARTIAL | Task detail: полные outcomes и artifacts |
| EP-023 | P2 | M | OPEN / OPEN | Schedules: timezone, missed fire и next run explain |
| EP-024 | P2 | M | OPEN / OPEN | Triggers: безопасная simulation и feedback loop limits |
| EP-025 | P1 | L | OPEN / OPEN | Webhook attempts/outbox и совместимость доставки |
| EP-026 | P2 | XL | OPEN / OPEN | Typed datasources и project manifest |
| EP-027 | P1 | M | OPEN / PARTIAL | Inspector tree, selectors, freshness и performance |
| EP-028 | P1 | M | OPEN / PARTIAL | Явный device/agent telemetry scope и inventory |
| EP-029 | P1 | L | OPEN / PARTIAL | Selected video end-to-end диагностика и управление |
| EP-030 | P2 | M | OPEN / PARTIAL | Original PNG и matching asset provenance |
| EP-031 | P1 | L | OPEN / OPEN | Thumbnail wall 128 вместо множества full video |
| EP-032 | P1 | L | OPEN / PARTIAL | Общие structured logs всех разрешённых sources |
| EP-033 | P1 | L | OPEN / PARTIAL | Byte-bounded backend log reads и global retention |
| EP-034 | P2 | M | OPEN / PARTIAL | Audit journal semantic outcome и redacted diff |
| EP-035 | P2 | M | OPEN / OPEN | Dashboard attention queue и actionable drilldown |
| EP-036 | P2 | M | OPEN / PARTIAL | Groups membership и bulk plan |
| EP-037 | P2 | M | OPEN / PARTIAL | Locations hierarchy UX и validation |
| EP-038 | P2 | M | OPEN / OPEN | Discovery capability-scoped onboarding |
| EP-039 | P2 | M | OPEN / PARTIAL | Users role preview, safety и access review |
| EP-040 | P2 | M | OPEN / PARTIAL | Configuration effective state и разделение policies |
| EP-041 | P1 | L | OPEN / PARTIAL | Release rollout receipts и каналы |
| EP-042 | P2 | XL | OPEN / OPEN | Generic resources вместо game domain assumptions |
| EP-043 | P2 | XL | OPEN / OPEN | Разделить account session и universal run |
| EP-044 | P1 | L | OPEN / PARTIAL | VPN assigned/applied/handshake/egress outcomes |
| EP-045 | P2 | XL | OPEN / PARTIAL | Versioned VPN provider adapters и rotation |
| EP-046 | P2 | XL | OPEN / DEFERRED_DESIGN | AI-ready schemas/runbooks и scoped artifacts |
| EP-047 | P1 | XL | OPEN / PARTIAL | Общая matrix500/1000 иresource leak gates |
| EP-048 | P1 | L | OPEN / PARTIAL | Тесты всех меню/форм/ролей иvisual states |
| EP-049 | P1 | L | OPEN / PARTIAL | Документация source/runtime/schema freshness |
| EP-050 | P1 | L | OPEN / OPEN | Alert delivery иsynthetic Android SLI |

## Дополнения из чата

### CHAT-01 · Возврат назад на прежнюю позицию

**ACCEPTED_FINITE** · EP-011, EP-015.

Browser Back и общая кнопка Back: каталог 2132.5 → 2132.5 px после route commit; память вкладки ограничена.

Остаётся: Нет обещания сохранения scroll после F5. Защита грязного черновика при browser Back/Forward остаётся открытой.

Доказательства: [ROUTE-SCROLL-RESTORATION](../audits/2026-10-09/ROUTE-SCROLL-RESTORATION.md).

### CHAT-02 · Свободные узлы и редактирование соединений

**ACCEPTED_FINITE** · EP-014, EP-015.

Detached add, palette drag/drop, явная вставка, разрыв/переназначение связи и Undo имеют конечную приёмку.

Остаётся: Semantic subgraphs/зоны orchestration/pipeline, полный conflict diff и все графы не приняты.

Доказательства: [STUDIO-INSTALLED-ACCEPTANCE](../audits/2026-10-07/STUDIO-INSTALLED-ACCEPTANCE.json), [STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.json).

### CHAT-03 · Доступность библиотеки на телефоне и компоновка

**PARTIAL** · EP-013, EP-014, EP-048.

Четыре compact panels, desktop library рядом с laboratory; 390×844, 844×390 и 1440×900 проверены.

Остаётся: В landscape общий fit длинной вертикальной цепочки делает узлы слишком мелкими; полная visual/a11y matrix открыта.

Доказательства: [STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.md).

### CHAT-04 · Палец мышью: MOVE поступает до отпускания

**ACCEPTED_FINITE** · EP-029, EP-020.

Текущий срез: PH010 на APK 10260 подтвердил прямые DOWN, MOVE и UP через 3015 и Tuna, включая жест после каждого из шести обрывов RTC. Серверных событий касания в этих жестах не было.

Предыдущая конечная приёмка PH011 / APK 10249: DOWN 1 / MOVE 5 / UP 1; wheel DOWN 1 / MOVE 1 / UP 1, capability и owner согласуются автоматически.

Остаётся: Конечные direct DOWN/MOVE/UP и восстановление после RTC-loss проверены на PH010/10260; это не нулевая задержка, не весь парк и не длительный idle/active soak.

Доказательства: [CONTINUOUS-VIEWER-FAULT-ISOLATION](../audits/2026-10-08/CONTINUOUS-VIEWER-FAULT-ISOLATION.md), [CONTINUOUS-INPUT-AUTOMATIC-UX](../audits/2026-10-08/CONTINUOUS-INPUT-AUTOMATIC-UX.md).

### CHAT-05 · Запись Home, Back, Recents, Menu

**ACCEPTED_FINITE** · EP-018.

PH011: четыре APK confirmed outcome в порядке записи, очередь сохранена при переключении панелей, late ACK после Stop обновляет исходную строку.

Остаётся: Подтверждение этих четырёх кнопок не закрывает весь rich recorder или все типы input.

Доказательства: [STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.json), [STUDIO-RECORDER-INSTALLED-ACCEPTANCE](../audits/2026-10-08/STUDIO-RECORDER-INSTALLED-ACCEPTANCE.md).

### CHAT-06 · Запись непрерывной траектории жеста

**PARTIAL**

APK82/UI15ce: one timed path per gesture; PH011/PH030 finite two-gesture recording/replay, native helper reuse and planned inter-gesture offset confirmed. PH011 held-path and idle-gap cancellation restore manual READY; media peers retained. Four installed package hashes. [Приёмка серии жестов](../audits/2026-10-16/POINTER-TIMELINE82-DELIVERY.md). · EP-018, EP-019.

Остаётся: Timing/jitter under load and other topologies, every MOVE execution proof, multitouch, rich XPath/pixel/crop evidence, keyboard recording and application-state equivalence remain open.

### CHAT-07 · Смешанная запись XPath → tap → системная кнопка

**ACCEPTED_FINITE** · EP-018.

UI60be6ecd/APIbe803773: PH01110249 tap → planned XPath → tap → APK-confirmed Back,4 строки; явный перенос6actions с2паузами,9узлов/8связей; Undo восстановилv1/3узла/2связи. Все4CI success, frontend1938tests/139suites.

Остаётся: Finite PH011 не подтверждает все устройства/rotation/clock changes/replay; MOVE/context bundle отдельно OPEN (CHAT-06/08), EP-018 остаётся OPEN/PARTIAL.

Доказательства: [STUDIO-CLOCK-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-CLOCK-INSTALLED-ACCEPTANCE.md), [STUDIO-RECORDER-CLOCK-FIX](../audits/2026-10-09/STUDIO-RECORDER-CLOCK-FIX.md).

### CHAT-08 · Запись контекста: XPath, зона, crop, цвет пикселя

**OPEN** · EP-018, EP-019, EP-027, EP-030.

Можно явно добавить выбранный XPath-кандидат; отдельный native PNG работает в принятом scope.

Остаётся: Автоматического pre-action tree/crop/pixel bundle со связанными кадром, командой и snapshot IDs нет. Нужны freshness, quotas, TTL и экспорт.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-09 · Исходный PNG

**ACCEPTED_FINITE** · EP-030.

Отдельный native capture: original Android → server → browser bytes/hash chain; пользователь разрешил считать screenshot рабочим.

Остаётся: Сравнение двух присланных файлов приостановлено пользователем. Matching assets/provenance и workflow artifacts остаются открытыми.

Доказательства: [DEVICE-CONTROL-AND-NATIVE-CAPTURE](../audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md).

### CHAT-10 · Веб обновляется при изменении данных

**PARTIAL** · EP-010, EP-050.

Fleet WS пакетно invalidates REST queries; скрытые вкладки/reconnect согласуются отдельно. Prometheus/fleet metrics обновляются polling 15 s.

Остаётся: Не каждая метрика имеет push producer; events connected не доказывает исправность Android или freshness каждого показателя.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-11 · 128 устройств: thumbnails, Connect all, синхронизатор

**OPEN** · EP-031, EP-047.

Текущая /stream wall использует full DeviceStream; grid до 64.

Остаётся: 128 thumbnails по 5/10 s, shared capture/budgets и Connect all/synchronized input с partial outcome/Stop требуют отдельной реализации и приёмки.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-12 · Наблюдение заполнения всего ПК без ручного угадывания

**OPEN** · EP-033, EP-047.

Текущий срез: Ограниченный непривилегированный collector28000 после перезапуска подтвердил125 последовательных samples; bounded24h/16MiB. C: после ремонта Healthy/OK,10 проверенных Git-объектов заменены. Потеря места не атрибутирована полностью; VSS недоступен в текущем окне.

Остаток: Whole-PC writer UNKNOWN: VSS unavailable, USN/ETW не запущены. Нет reboot autostart; после deadline потребуется bounded restart/health. Resource soak/retention и RAM acceptance открыты.

[Новая сверка source/CI/install](../audits/2026-10-11/STREAM-IDLE-PROGRESS-RECOVERY.md).

Предыдущие конечные наблюдения и исходные требования:

Limited observer возобновлён10Oct00:14→12:34UTC,371×120s/16MiB.
171 complete samples до05:54:43UTC: C:−7716163584B при неизменных Docker VHDX
identity/allocation234731077632B. PID32064/process creation/command/source сверены.
Прежний разрыв после23:59 не покрыт; точный writer всего C: ещё UNKNOWN.

Остаётся: Whole-PC writer UNKNOWN: VSS unavailable, USN/ETW не запущены.
Нет reboot autostart; после deadline нужны bounded restart/health,
resource soak/retention и RAM acceptance.

Доказательства: [STORAGE-OBSERVER-RESUME](../audits/2026-10-10/STORAGE-OBSERVER-RESUME.json), [STORAGE-OBSERVER-CONTINUITY](../audits/2026-10-10/STORAGE-OBSERVER-CONTINUITY.json), [STORAGE-WINDOW-COMPLETION](../audits/2026-10-08/STORAGE-WINDOW-COMPLETION.json).

### CHAT-13 · Единая автоматизация и универсальные ресурсы

**OPEN** · EP-021, EP-026, EP-042, EP-043.

Сценарии, задания, orchestration и pipeline доступны как отдельные текущие сущности.

Остаётся: Общий workspace/references, универсальные project resources/connectors и semantic composition ещё не приняты.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-14 · Подключаемые VPN providers и AI

**OPEN** · EP-045, EP-046.

Проверены исходные каталог/revisions/RLS/UI и закреплённый SDK. Собраны три
hardened native ABI; пройдены конечные root-TUN AWG/HTTP на PH011 и WG/DNS на PH030,
crash/UID isolation и контрольный UID Sphere. Основной VpnService не установлен.

Остаётся: Единый APK с VpnService/consent/revoke/protect, DNS/IPv6/boot/sleep/network
acceptance, durable apply/rotation journal, scripts/orchestration и rollout; AI отдельно.

Доказательства: [Android candidate и PH030](../audits/2026-10-21/VPN-ANDROID-PROVIDER-CANDIDATE.json),
[VPN-каталог](../audits/2026-10-21/VPN-CATALOG-NATIVE-CANDIDATE.json),
[эксплуатация](VPN-PROFILES.md), [AI-READINESS](../architecture/AI-READINESS.md),
[NitroGen/LAN — аудит 16 октября](../audits/2026-10-16/NITROGEN-READINESS.md).

### CHAT-15 · Прямой browser ↔ Android transport

**PARTIAL**

UI4b39c385 / API969a7444 installed on3015/Tuna. APK76 completed OTA on15 devices;14 exact installed hashes,1 command/version-only proofs;6 offline pending. Finite local two-client mouse/touch/native keys, ten Tuna clients, three forced peer recoveries, actual agent-process restart and Unicode/chords/composition/fullscreen with original IME restoration accepted. Not20+, real phone/hotspot, WAN/TURN, broker-offline autonomy, audio, server-fallback full keyboard, full local CI or production SLA.

Остаётся: 20+, physical phone/hotspot/LAN/WAN/TURN and long soak; broker-independent session authorization and remaining transport recovery cases.

[Текущий протокол](../audits/2026-10-15/DIRECT-KEYBOARD76-OBSERVATION.json).

## Прямой browser ↔ Android media: до production допуска

Исследование и реализация уже начаты по прямому разрешению пользователя.
UI331/API983 и 15 APK60 установлены; конечные прямое видео, ввод и возврат после RTC-loss проверены на PH010. C: после ремонта Healthy/OK. Полная приёмка сетевой матрицы, latency и длительного soak ещё впереди.

Все41 будущие возможности продукта не блокируют этот этап автоматически.
До production нужны session/auth/geometry и control-owner fences, реальная
проверка удерживаемого CANCEL и fresh STARTUP, ближайшего выбранного ICE route,
localhost/LAN/Internet и TURN fallback. Host-first ICE не обходит VPN или firewall;
прямой маршрут доступен только для реально достижимой пары.

Нужны отдельные capture/encode/network/decode/presentation и input-to-picture
измерения, длительный idle/action/reconnect soak и ресурсные бюджеты. Android
execution сценариев и серверные task receipts сохраняют свою семантику.
Online badge, echo RTT и успешная сборка не доказывают эти критерии.
[Архитектура](../design/BROWSER-DIRECT-TRANSPORT.md) ·
[Проверенная подготовка](../audits/2026-10-11/STREAM-IDLE-PROGRESS-RECOVERY.md).

## Как закрывать работу без потери истории

- Не менять frozen baseline/старый JSON receipt. Добавить датированное evidence.
- В STATUS-REGISTRY обновить acceptedScope/remaining, source/test/install/live
  границы; для полного EP closure проверить **все** исходные acceptanceCriteria.
- Частичный пользовательский workflow закрывать в CHAT-ID с указанным scope;
  родительский EP остаётся OPEN, пока его остальные критерии не выполнены.
- Сослаться из current-state/readiness на новую запись. Старые installs и CI
  остаются историей своих SHA. После изменения запустить checker из DOCUMENTATION.
- Не переносить successful CI одного SHA, закрытие user workflow или финальный
  readback на другой source, весь парк либо непрерывный SLA.

### CHAT-16 · Стабильный APK1.3 и расширение без лишних переустановок

**PARTIAL**

Текущий срез: APK68/10268 подтверждён по установленному SHA и completed OTA на14 доступных устройствах; семь офлайн, включаяPH030, не подтверждены. Dev/enterprise combined profile: 1162 cases каждый, 0 failures/errors, 3 skipped каждый. Это dev/canary, стабильный1.3 ещё не выпущен.

**Историческая запись 11 октября, до текущей установки.** Versioned DAG/discovery/OTA boundaries reviewed. The older PH03010251 finite RTP report is historical; current fleet follow-up verifies15 APK54 hashes including PH030. Combined source522 APK55 debug CI passed; configured pilot signing/install and stable1.3 promotion are still pending.

Остаток: Idle reliability, native lifecycle/resources, direct path and capability matrix acceptance, production signer verification and staged OTA promotion.

[Сверка и следующий допуск](../audits/2026-10-11/STREAM-IDLE-PROGRESS-RECOVERY.md).

### CHAT-17 · Broadcast500 и CSS preload публичного веба

**PARTIAL**

Две причины500 воспроизведены независимо, исправлены и установлены в UI/API369.
[Source audit](../audits/2026-10-10/BROADCAST-BINARY-PRESENCE.md),
[CI registry correction](../audits/2026-10-10/CI-REGISTRY-LIMIT.md).
Все4 exact369 CI success; backend3428/252subtests, frontend1966. Реальный isolated
PostgreSQL/Redis test подтвердил202/commit/admission; live404 после чтения presence
проверен на обоих адресах без массового запуска. [Installed receipt](../audits/2026-10-10/BROADCAST-INSTALLED-ACCEPTANCE.md).
Остаток: CSS в публичном каталоге/графе
загружается; исходное предупреждение не воспроизвелось в этом окне. Idempotency,
большой парк и unknown presence требуют самостоятельных контрактов.

### CHAT-18 · Несколько зрителей: управление и presence по вкладкам

**PARTIAL**

APK76/UI4b39/API969: ten direct participants,40 native system keys,gestures,takeover and9 survivors for30s; two actual keyboard owners verified earlier on the same APK.

Остаётся: 20+, real physical emulator input and phone/hotspot/geographical matrix; longer shared-keyboard and video soak.

[Текущий протокол](../audits/2026-10-15/DIRECT-KEYBOARD76-OBSERVATION.json).

### CHAT-19 · Физическая клавиатура, IME и звук устройства

**PARTIAL**

Direct fullscreen physical keys,Unicode,Backspace,Ctrl+A,composition and native game-key edges are implemented and actual Android fields verified; prior IME restored. Home/Back/Recents/Menu use the same authorized media peer.

Остаётся: Server-fallback full keyboard; recorder/DAG Unicode playback; broader IME/OS-shortcuts/key-repeat/background matrix; optional default-off audio.

[Текущий протокол](../audits/2026-10-15/DIRECT-KEYBOARD76-OBSERVATION.json).

### CHAT-20 · Последние десять сеансов и автоматическая диагностика клиента

**PARTIAL**

Предыдущий срез: В UI331/API983/APK60 установлены последние 10 сеансов, 32 KiB/session, 15 samples/category, 7 days; авторизация и private/no-store проверены на обоих адресах. Конечные direct/native, presentation и suppression counters наблюдались на PH010. Неподтверждённое MOVE не выдаётся за выполненное.

**Историческая запись 11 октября, до текущей установки.** Bounded automatic diagnostics and last10 sessions were installed earlier. Source522 preserves10 sessions, 32KiB/session,15 samples/category,7days; adds presentation-stall reason and four compatible native measurements. Worst-case ages/counters retain latest observations and session close in45 local tests; new telemetry runtime not installed.

Остаток: End-to-end frame correlation, физическая смена сети, длительная idle/active/resource приёмка, точные категории timeout и проверка browser↔APK разных сетей остаются открытыми.

[Сверка и следующий допуск](../audits/2026-10-11/STREAM-IDLE-PROGRESS-RECOVERY.md).

### CHAT-21 · Скачать всегда актуальный APK и официальный LDPlayer

**ACCEPTED_FINITE**

Latest signed canary APK76 downloaded fully on both origins with exact SHA/bytes. Ordinary Android channel is unchanged; download and installation proofs are distinct.

Остаётся: Внешние latest URL здесь не проксируются; скачивание не подтверждает установку. Stable promotion, все роли и offline fleet остаются отдельными открытыми gates.

[Текущий протокол](../audits/2026-10-15/DIRECT-KEYBOARD76-OBSERVATION.json).

### CHAT-22 · Тёмный адаптивный вход и сохранение темы рабочего пространства

**ACCEPTED_FINITE**

Историческая приёмка UIed9 на обоих адресах: пять viewports, 48px controls, reveal/hide, real login и сохранение light/spacious проверены; dark login и default neo-dark подтверждены.

Остаток: Живой MFA-enabled user, все роли, screen reader, zoom и полная theme/accent/density matrix не приняты.

[Установленная доработка](../audits/2026-10-12/APK-DOWNLOAD-AND-LOGIN.md).

### CHAT-23 · Стоимость CI и локальные проверки с результатами на GitHub

**PARTIAL**

Eight active YAML workflows disabled; all nine repository YAML workflows inactive at readback; three current hosted runs cancelled, prior parallel hosted runs acknowledged. Local exact-source Android82 dev/enterprise1250 tests, previous unchanged UI/API15ce full suites and commit statuses recorded. [Остановка hosted CI и исправление прежнего утверждения](../audits/2026-10-16/HOSTED-ACTIONS-DISABLED.md).

Остаётся: Automatic local per-push queue, reboot recovery, full release/deploy/security/Linux parity and durable artifact/log retention remain open. Earlier hosted consumption is not reversed; account billing is not accepted.

### CHAT-24 · Настройки качества, source FPS и краткая строка параметров

**PARTIAL**

Установлены профили, лимиты FPS/битрейта и краткая строка маршрута, RTT, размера, фактических FPS и битрейта. PH010 подтвердил native target 60 и 54–59 декодируемых FPS на обоих адресах, изменение профилей без нового peer/capture и адаптивную панель. Lossless, все аппаратные варианты и 60 FPS при любой нагрузке не заявлены. [Конечная приёмка](../audits/2026-10-13/DIRECT-SOURCE-QUALITY-DELIVERY.md).

### CHAT-25 · Установленный localhost/LAN peer при потере Интернета/сервера

**OPEN**

Совместный direct v2 input уже установлен. Автономные bounded grants пока существуют как модель: установленный media/input peer всё ещё зависит от продления server lease. Нужны независимое время жизни broker/peer и физическая проверка WAN loss при сохранённом локальном пути.

### CHAT-26 · Месячная история инфраструктурных метрик и фильтр дат

**OPEN**

Отложено пользователем. Last10 stream sessions/7days не доказывают месячную историю инфраструктуры. Требуется аудит historian storage, retention, durability при restart и calendar/range UI.


### CHAT-27 · Fullscreen stream, полупрозрачная навигация и touch-клиент

**PARTIAL**

Installed native fullscreen, accessible44px Android tray and explicit touch toggle; actual browser mouse/touch passed390x844/844x390 on3015/Tuna without remounting media elements or replacing the peer.

Остаётся: Real phone/hotspot,safe-area/zoom and physical visibility/network changes; broader keyboard/composition/browser matrix. Fullscreen direct keyboard is now implemented and finite accepted.

[Текущий протокол](../audits/2026-10-15/DIRECT-KEYBOARD76-OBSERVATION.json).

### CHAT-28 · Визуальный аудит, размеры, hover/pin sidebar, темы, логотип и glass

**PARTIAL** · Новый сквозной scope, отдельно от исходных 50 product items.

Готов [аудит](../audits/2026-10-15/UI-UX-VISUAL-AUDIT.md): 29 шаблонов страниц,127 состояний,2468 снимков кнопок/ссылок,509 исходных объявлений кнопок и47 DialogContent. Изменения интерфейса не устанавливались; реализация20 пунктов и недоступные условные/роль/phone-keyboard состояния остаются открытыми.

### CHAT-29 · Android файловый менеджер: папки, upload/download, очередь и resume

**OPEN** · Новый функциональный scope; готов [контракт](../design/ANDROID-FILE-MANAGER.md).

Текущий APK76 не содержит общего файлового протокола. Нужны Android provider/capabilities,API,explorer и фактическая приёмка transfer/resume/integrity/cleanup без регрессии стрима и управления. Это не поставленный файловый менеджер.

### CHAT-30 · Системный профиль Android не должен конфликтовать с прямым вводом

**OPEN** · Сообщение PH025 getprop/device_input_busy сопоставлено с общим input ownership в shell.

Read-only profile должен выполнять типизированное чтение в отдельном worker; новый запрос на PH025 не запускался и APK не обновлялся. Нужна фактическая параллельная проверка после исправления.


### CHAT-31 · Все настройки UI синхронизируются по аккаунту

**OPEN**

Requirement and source audit recorded; implementation not accepted.

Остаётся: Versioned server profile/ETag, identity-bound local cache, all preferences, conflict/offline/multi-browser acceptance.

[Контракт, очередность и критерии](../design/CLIENT-STUDIO-PLATFORM.md).


### CHAT-32 · Проверка неизменяемого несохранённого сценария на выбранном Android

**OPEN**

Requirement and source audit recorded; implementation not accepted.

Остаётся: Immutable draft execution endpoint, server validation/RBAC/capability and input handoff; do not silently publish or mutate current script.

[Контракт, очередность и критерии](../design/CLIENT-STUDIO-PLATFORM.md).


### CHAT-33 · ИИ-конструктор: именованные ключи, полный контракт и визуальный proposal

**OPEN**

Requirement and source audit recorded; implementation not accepted.

Остаётся: Encrypted named model connections, current contract/context assembly, strict proposals/diff and independent server validation; no actual inference accepted.

[Контракт, очередность и критерии](../design/CLIENT-STUDIO-PLATFORM.md).


### CHAT-34 · Динамические проекты и изолированные обновляемые плагины

**OPEN**

Requirement and source audit recorded; implementation not accepted.

Остаётся: Project resources/revision/outbox without API restart; isolated versioned plugin SDK and lifecycle, migrations/rollback/drain. Python/DDL deployment is separate.

[Контракт, очередность и критерии](../design/CLIENT-STUDIO-PLATFORM.md).


### CHAT-35 · Сценарий при других управляющих direct клиентах

**PARTIAL**

APK80 и веб ed220169 прошли конечные PH011-проверки с двумя клиентами, отменой,
удерживаемым касанием и третьим поздним зрителем. Видео сохраняет media peers;
после задания подтверждён новый ручной READY и native Home.

Остаётся: 20 клиентов, длительная нагрузка и разные физические сети, быстрый cancel
внутри длинных действий. Полные траектории — отдельный открытый контракт.

[Поставка и границы](../audits/2026-10-16/AUTOMATION-INPUT80-DELIVERY.md).

### CHAT-36 · Имена, описания, группы нод и полнота параметров

**OPEN**

Зафиксированы требования CS-16/17/18: отображаемое имя отдельно от routing ID,
сохраняемые метаданные, undo/export/import, визуальные группы и версионированные
исполняемые блоки, аудит параметров и реализации всех типов нод. Не реализовано.

[Контракт и критерии](../design/CLIENT-STUDIO-PLATFORM.md).
