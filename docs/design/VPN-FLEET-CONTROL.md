# VPN и прокси для парка: данные, распределение и автоматизация

22 октября 2026 · план развития и результаты разбора исходников. Этот документ
разделяет установленное, новый исходный код и требуемую приёмку. Он не объявляет
Android kill switch, прокси, внешний allocator или оркестрацию готовыми.

## Опорная точка

Установлены UI `37926bd3`, API `7d2a6846`, зашифрованный каталог и миграция
`20261021_vpn_profiles`. Каталог использует отдельный nonowner DB-login; основная
роль API по-прежнему привилегированная. APK83 остаётся текущим агентом, APK84 —
локально собранный кандидат. Точная поставка и восемь реальных экранов:
[live delivery](../audits/2026-10-22/VPN-CATALOG-LIVE-DELIVERY.md).

Новый код этого этапа добавляет пакет до 100 профилей, серверную предварительную
проверку, атомарную запись и read-only восстановление квитанций. Полный контракт:
[VPN-PROFILES](../operations/VPN-PROFILES.md). Это библиотека конфигураций;
появление записи в ней не означает подключённое устройство.

Дальнейшая архитектура продолжает [VPN/egress](VPN-EGRESS-ARCHITECTURE.md) и
[контракт результатов](../operations/VPN-CONTROL-OUTCOMES.md).

## Проверенные внешние ограничения

Android разрешает включать в `VpnService` конкретные приложения. Транспортные
сокеты самого VPN надо защищать от попадания обратно в TUN, а управляющее
приложение исключать из выбранных UID. Работоспособность после revoke/смены сети
проверяется отдельно от создания интерфейса.
[Android VPN](https://developer.android.com/develop/connectivity/vpn).

`TrafficStats` начиная с Android 7 ограничивает чужие UID. `NetworkStatsManager`
требует Usage Access для статистики других приложений; детализация исторических
бакетов измеряется часами и не подходит для мгновенной скорости. Эти API не
заменяют друг друга. [TrafficStats](https://developer.android.com/reference/android/net/TrafficStats),
[NetworkStatsManager](https://developer.android.com/reference/android/app/usage/NetworkStatsManager).

У AOSP есть eBPF accounting, но его наличие зависит от ядра и сборки Android;
для старых эмуляторов нельзя считать `/proc/net/xt_qtaguid/stats` универсальным.
[AOSP traffic monitoring](https://source.android.com/docs/core/data/ebpf-traffic-monitor).

SOCKS5 определяет отдельный `UDP ASSOCIATE`. Наличие HTTP/SOCKS login ещё не
доказывает поддержку игрового UDP. Для Android-приложений нужен TUN-to-proxy
движок; системный HTTP proxy этого не обеспечивает. Кандидат для отдельной
оценки — `hev-socks5-tunnel`, где предусмотрены Android и TCP/UDP. В APK он
сейчас не встроен. [RFC 1928](https://www.rfc-editor.org/rfc/rfc1928),
[исходники hev](https://github.com/heiher/hev-socks5-tunnel).

В upstream Amnezia зарегистрирован незакрытый отчёт Android 16: при добавлении
приложения в split tunneling handshake перестаёт доходить до сервера. Это один
отчёт пользователя, не доказательство причины наших разрывов. Следствие для
приёмки Sphere: отдельно проверять handshake, выбранный UID и control bypass.
[Issue #2802](https://github.com/amnezia-vpn/amnezia-client/issues/2802).

Версия SDK/приложения и версия конфигурационного протокола — разные сущности.
Официальное описание изменений: [AmneziaWG](https://docs.amnezia.org/documentation/amnezia-wg/).
Обновление модуля нельзя принимать только по номеру версии: нужны fixture разных
поколений, native ABI, handshake/data, сохранение обхода Sphere и fault tests.

## Разбор наших соседних репозиториев

Изучены выбранные документы, определения API/services и тесты на закреплённых
ревизиях. Чужие серверы не вызывались, конфиги из `awg-clients`, state-файлы и
секреты не импортировались. Надписи «в проде» в их README остаются утверждениями
этих репозиториев, не приёмкой текущего Sphere.

| Репозиторий / ревизия | Что проверено | Решение для Sphere |
| --- | --- | --- |
| `mobileproxy.space_rust` · `af54055874579f4c0308f7da6f366d41674515bd` | `docs/LEASE_V2.md`, `ENDPOINT_UNIQUENESS.md`, `lease_registry.py`, `api/proxy_export.py` | Использовать контракт lease/hold/TTL и учёт endpoint identity через адаптер; не копировать node shell routing |
| `wg-tunnel-router` · `ea11e1c5c1d9e33df301bd10216d4a6f7e99b8de` | `api/ACCOUNTS_API.md`, routers tunnels/stats, `awg_service.py` | Отдельный adapter для inventory/live state/rotate; не запускать его root network mutations в Android/API Sphere |
| `vpn_validator` · `8feea130c1aaf8da6aa89e93ce474115045045f1` | README, определения `main.py`, `config_hold.py`, тесты lease v2 | Разделять `valid`, `invalid`, `timeout/unchecked`, временный hold и окончательный auth verdict |

Ссылки доступны владельцам приватных репозиториев:
[mobileproxy](https://github.com/RootOne1337/mobileproxy.space_rust/tree/af54055874579f4c0308f7da6f366d41674515bd),
[router](https://github.com/RootOne1337/wg-tunnel-router/tree/ea11e1c5c1d9e33df301bd10216d4a6f7e99b8de),
[validator](https://github.com/RootOne1337/vpn_validator/tree/8feea130c1aaf8da6aa89e93ce474115045045f1).

Особенность router API: бизнес-ошибка может приходить в HTTP 200 с `success:false`.
Адаптер обязан проверять envelope, а не только статус HTTP. `timeout` у валидатора
не равен плохому аккаунту. В mobileproxy уникальность `remote` решает задачу
выходных адресов, но для WG требуется ещё уникальность клиентского публичного
ключа. Один серверный endpoint может обслуживать много независимых WG peers;
запрещать общий endpoint всем WG-клиентам было бы ошибкой.

## Модель, на которой можно строить сценарии

| Сущность | Назначение и владелец факта |
| --- | --- |
| Provider adapter | Версионированные возможности: WG/AWG, SOCKS5 TCP/UDP, HTTP CONNECT, DNS, IPv6, ротация, ограничения; не произвольный shell plugin |
| Profile + revision | Неизменяемая конфигурация и политика приложений; ciphertext в каталоге |
| Credential/client identity | Отдельная сущность от имени файла; уникальность ключа WG проверяется до применения |
| Exit observation | Фактически наблюдённый IPv4/IPv6, ASN/страна при разрешённом probe, время/источник; не предположение по endpoint |
| Pool | Состав, теги, вместимость, exclusivity/stickiness, cooldown, квоты, политика замены |
| Lease | Tenant, identity, device, revision, fencing generation, expires/hold reason; один владелец активного намерения |
| Device desired state | Какая revision/policy должна работать; отдельно фактический отчёт Android |
| Operation journal/outbox | UUID, actor, source UI/script/pipeline, ожидаемая revision/lease, deadline, dispatch/ACK/final outcome |
| Observation | Источник, device/session/provider epoch, собственное время измерения, freshness, доступность |

Импорт профилей уже реализован. Остальные новые сущности не надо подменять
существующей таблицей peers: она не является общим lease registry. Нужна отдельная
добавочная миграция с явной проверкой tenant/RLS и recovery, как у каталога.

## Пакеты, прокси и распределение

Текущий формат пакета — несколько `.conf`. Будущие входы: ZIP с manifest,
текстовые SOCKS/HTTP URI, provider inventory API и ссылки на существующие secret
references. У каждого импортёра отдельные ограничения, версия формата и проверка
возможностей. Для ZIP обязательны ограничения compressed/uncompressed bytes,
числа/длины имён, вложенности, запрет symlink/path traversal/дубликатов; архив не
распаковывается на произвольный путь. Это ещё не реализованный endpoint.

Пользователь выбирает устройства или группу, pool и стратегию: закреплённая
пара, один-к-одному, детерминированное равномерное распределение, sticky choice
или явное ручное назначение. До исполнения показываются существующий/новый
выход, конфликт identity, недоступные возможности, устройства без consent и
остаток pool. План имеет hash/revision и срок; применение повторно проверяет
эти условия. Изменившаяся группа не расширяет уже подтверждённый frozen plan.

Повторное назначение того же WG client key другому активному устройству запрещено.
Общий IP возможен, если это явная разрешённая политика pool; «100 профилей» не
означает «100 разных IP». Внешний `rotate` может сменить адрес одновременно всем
клиентам одной мобильной proxy identity — blast radius должен быть в preview.

Никакой сетевой операции при простом импорте. Большие раздачи выполняются волнами
с лимитом параллелизма, timeout, jitter, retry budget и circuit breaker. Неизвестный
исход предыдущей операции удерживает lease; TTL сам по себе не доказывает, что
старый Android перестал пользоваться ключом. Перенос требует подтверждённого
release/reconcile или явного административного решения с fencing и аудитом.

## Какие метрики нужны и как их честно показывать

| Метрика | Возможный источник | Ограничение |
| --- | --- | --- |
| Tunnel RX/TX, handshake | Native provider | Сессия/эпоха провайдера; отдельно время sample и доставки |
| Скорость RX/TX | Дельта двух свежих native samples | После reset/reconnect результат неизвестен до новой пары; negative delta не clamp в «0» |
| Расход конкретного приложения | UID accounting Android с capability/permission | Shared UID объединяет пакеты; источник может включать весь трафик UID, а не только VPN |
| Исторический расход | NetworkStatsManager с Usage Access | Не выдавать за real-time, не выполнять на main thread |
| Трафик выбранных UID в TUN | Проверенный root/eBPF/legacy accounting adapter | Зависит от ядра, IPv6, VPN adjustment; не складывать outer и inner как независимый расход |
| DNS/IPv4/IPv6 exit | Конечный probe из выбранного приложения/UID | Probe из Sphere показывает обход Sphere, а не маршрут игры |
| RTT/loss/jitter | Явный ограниченный probe | Handshake age, ICMP и RTT WebRTC — разные измерения |
| Control/video/input route | Собственная диагностика Sphere | Не включать её bytes в «расход игры» |
| CPU/RAM/restarts/provider PID | Процесс Android | Отсутствующий PID/permission — неизвестно, не ноль |
| Kill-switch status | Снимок guard + конечный fault probe | Существование правил само по себе не подтверждает отсутствие утечки |

Предлагаемый telemetry envelope: schema version, device/provider/session/boot
identity, UID/package mapping revision, sampledAt + receivedAt, monotonic interval,
source/capability, units, scope и unavailable reason. Integer counters передаются
в пределах безопасного диапазона JSON или строкой в новой версии контракта.
Переустановка меняет UID; смена package mapping закрывает прежнюю серию.

Сэмплер должен иметь конечный timeout и бюджет нагрузки. Частые `su` вызовы с
уведомлениями недопустимы: permission denial останавливает root adapter до явного
изменения capability. Системные eBPF maps не читаются неподдерживаемым обходом.
Без достаточного источника веб показывает «Нет данных / требуется разрешение».

Для fleet totals считать только совместимые интервалы и показывать покрытие,
например «18 из 21 устройств». Не суммировать перезапущенные cumulative counters
и stale snapshots. История хранится агрегатами с retention/downsampling, без
пакетов, адресов посещённых сайтов и содержимого игры. Период/часовой пояс и
отдельные измерения ingress/egress сохраняются в настройках аккаунта.

## Kill switch и сохранение связи Sphere

Цель: выбранные приложения остаются заблокированы при сбое туннеля, а Sphere,
видео, ввод, enrollment и OTA продолжают работать напрямую. Это требует UID
изоляции; список IP сервера не покрывает LAN, roaming, IPv6 и новые direct peers.
Android lockdown и выборочный root guard — разные механизмы. На Android 9 также
нельзя ссылаться на API проверки lockdown, добавленные только в Android 10.
[VpnService reference](https://developer.android.com/reference/android/net/VpnService).

В коде уже есть изолированный `:vpn` процесс, private Binder и root guard v3.
Отдельный root fixture пережил падение процесса с блокировкой выбранного UID и
живым control UID. Основной APK должен пройти это заново: apply, pause/resume,
rotate, revoke consent, kill provider, kill main process, reboot, обновление,
смена Wi-Fi/mobile, закрытие endpoint, DNS/IPv6 failure и устаревший ACK.
Без этого capability исполнения остаётся закрытой.

В VPN входит только выбранный application data plane. Адаптер не меняет глобальный
default route, AOSP fwmark, NAT/FORWARD хоста, домашний VPN или системный proxy
браузера. Исключение управляющего UID надо проверять по фактическому package UID
и сети сокетов, а не по отображаемому имени приложения.

## Скрипты, pipelines, ручные операции

Все входы должны обращаться к одному operation service. Ноды представляют
типизированные операции `allocate`, `apply`, `wait_verified`, `pause`, `resume`,
`rotate`, `release`, `probe`, `wait_egress_change`. Имена здесь — предлагаемый
контракт, не утверждение о существующих action types. UI и AI не получают путь
обойти capabilities или проверку lease.

Параметры: pool/profile reference, замороженный device set, package policy,
lease/stickiness, timeout/retry/cooldown, нужные DNS/IPv6/UDP возможности,
ожидаемый egress и failure branch. Отправка, принятие агентом и подтверждённое
сетевое состояние — отдельные результаты. Скрипт не хранит приватный конфиг.

Сценарий пользователя выражается данными: закончить этап приложения → освободить
старый session/lease по политике → выбрать новый выход → дождаться подтверждения →
запустить следующий этап. Имена игр и понятие «аккаунт докачался» не добавляются
в core VPN. Поведение при утрате API/lease service определяется явно: не запускать
новую ротацию, удержать проверенное локальное состояние/guard, затем reconcile.

## Раздел VPN в вебе

Существующие четыре вкладки остаются рабочей основой. Дополнительная детализация
появляется из проверенных данных, а не декоративных графиков:

- Подключения: одно устройство/группа, текущий и желаемый выход, причина состояния,
  native freshness, расход/скорость, consent, guard, control bypass, событие и операция.
- Профили: single/bulk import, версии, архив, pool membership и конфликты identities.
- Пулы/выходы: доступность, leases/capacity, hold/cooldown, наблюдённый IP, preview раздачи.
- Трафик: UID приложения, source/permission, периоды, покрытие и отдельные tunnel/control серии.
- Инфраструктура: адаптер, версия, readiness, договорённые provider limits, bounded диагностика.

Широкие массовые действия имеют preview и единый progress drawer; на телефоне
заголовок/действия закреплены, результаты прокручиваются. Нужны отмена ещё не
отправленных волн, read-only recovery неизвестных операций, сквозной operation ID
и журнал без секретов. Настройки отображения относятся к аккаунту, не к ключам.

## Порядок внедрения и условия выхода

| Этап | Результат | Приёмка |
| --- | --- | --- |
| 1 · Catalog batch | Новый код готов к регрессиям/поставке | 100 элементов, rollback late conflict, reverse concurrent order, minimal-role RLS, lost response, mobile visual review |
| 2 · Main APK provider | Один встроенный WG/AWG provider | Hosted ordinary/release/canary CI; локальная подпись и OTA; PH030 lifecycle/fault/control bypass |
| 3 · Journal/leases/outbox | Общий физический исполнитель | Exactly-bound intent, crash/restart reconciliation, unique client identity, expired lease without split ownership |
| 4 · Metrics adapters | UID и tunnel источники | Android 9 emulator + современный физический Android, permission denied/shared UID/reboot/VPN double-count fixtures |
| 5 · Pools and allocator | Manual/frozen plans/automatic waves | 100 синтетических assignments, partial failure, cancellation, quota, egress reuse policy |
| 6 · Proxy providers | SOCKS5 UDP и необходимые другие форматы | Сначала transport/DNS/IPv6; затем per-app isolation; никаких обещаний игрового UDP по одному HTTP 200 |
| 7 · Orchestration | Те же операции из нод и pipelines | Versioned scripts, recovery, retry budget и все failure branches без захардкоженной игры |

Каждый этап сохраняет точные source/image/APK hashes и отдельную квитанцию.
Прохождение CI не означает, что APK установлен или VPN пережил падение. Поставку
и runtime-приёмку записываем отдельно; старые замеры не переписываем новым успехом.
