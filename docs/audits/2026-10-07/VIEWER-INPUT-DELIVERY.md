# Viewer input: установленное исправление и живая проверка

Дата: **7 октября 2026, Asia/Yekaterinburg**. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Статус: **UI и API a41c4e6 установлены на локальном pilot 3015**.
Full source: `a41c4e64bf569a7518d34606da0facbba32f77e6`.

[Проверяемый runtime/CI/browser receipt](VIEWER-INPUT-INSTALLED-ACCEPTANCE.json) ·
[Исходный дефект и контракт](VIEWER-INPUT-ADMISSION.md) ·
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Инструкция Studio](../../operations/SCRIPT-STUDIO.md).

## Изменение поведения

Некорректный discrete input отклоняется до Android dispatch. Отсутствующие
координаты не превращаются в0/0, boolean/string/float не преобразуются в integer,
malformed JSON и неподдержанный тип не удаляют зрителя из видеосессии.
Сервер возвращает фиксированный код и причину без отражения пользовательского
текста. Веб отделяет отказ команды от транспортной ошибки видео; уведомление
можно закрыть. Это не continuous touch и не исправление всех причин задержки.

## Тот же проверенный image, без локальной пересборки

| Слой | Exact CI | Проверки | Время установки UTC |
| --- | --- | --- | --- |
| Frontend | [37544582302](https://github.com/RootOne1337/sphere-platform/actions/runs/37544582302), attempt1 | 1695 tests /133 suites, types/build, 26 packaged pages /73 assets | 6 октября23:15:49 |
| Backend | [37544582292](https://github.com/RootOne1337/sphere-platform/actions/runs/37544582292), attempt1 | 3097 passed /37 skipped /193 subtests, 2 warnings, coverage80.43%; все6jobs success | 7 октября02:59:21 |
| Android | [37544582396](https://github.com/RootOne1337/sphere-platform/actions/runs/37544582396), attempt1 | tests/lint/signed release smoke success; APK не устанавливался | — |
| Preview guard | [37544582342](https://github.com/RootOne1337/sphere-platform/actions/runs/37544582342), attempt1 | success; не VPS production deploy | — |

Config digest каждого image получен **независимо из authenticated CI job log**.
Downloaded ZIP сверён с GitHub artifact SHA-256; затем проверены receipt,
bounded gzip/tar, config/source/run/attempt и containerd manifest/config binding.
Frontend gzip120838690B, backend gzip236131291B. Backend ZIP потребовал два
конечных transfer attempts: первый остановился по300s deadline, второй продолжил
только созданный нами partial145752064B с exact HTTP206 Content-Range.
**Полный**, а не prefix digest совпал до admission. Это не retry установки или
Android input. Временные ZIP удалены; проверенные gzip и прежние images сохранены.
Local rebuild, raw tar и Docker prune не выполнялись.

Default read-only plans проверили owner/config/environment и host resources.
Установка последовательно заменила только review-ui, затем только backend.
Каждый шаг сохранил45 остальных контейнеров. Backend source delta — ровно
WS router и pure viewer_input.py; dependencies/bootstrap/RBAC/connection manager
не заменялись. SQL head `20261006_script_catalog_metadata`, четыре mounts,
environment и OTA hash сохранены; миграций и обновления APK не было.
Rollback images retained; отказа установки/rollback в этом прогоне не было.

## Живой transport canary PH010

После проверки API revision и readiness на одном authenticated WS проверены:

1. click без y — `invalid_parameter`;
2. boolean x — `invalid_parameter`;
3. JSON array — `invalid_message`;
4. malformed JSON — `invalid_message`;
5. `touch_down`, который ещё не поддерживается, — `unsupported_message`.

Все пять отказов получены на **том же соединении**. После них получены5 binary
messages /35568B и позднейший server ping с pong; canary завершён за10047ms,
соединение закрыто. Отправлены только auth, malformed inputs, один keyframe
request и pong. **Корректные Android input commands не отправлялись.**
Viewer lifecycle/keyframe — реальные stream-control команды, а не исполнение
сценария. Binary transport не декодировался этим probe; это не moving FPS,
визуальная плавность, input ACK или input-to-rendered-frame latency.

Все14 online agents имеют heartbeat и connected_since после замены API.
Всего19 зарегистрированных устройств,5 offline; это конечный reconnect check,
не доказательство исправности выключенных устройств или многочасового soak.
Каталог25 сценариев и fingerprint сохранены; running/assigned/queued tasks0.
Contract1.0/32 rules: valid draft200, tap без coordinates422, anonymous401.
Новые scripts/versions/tasks не создавались и не исполнялись.

## Реальный браузер и границы визуальной проверки

На native1280×720 открыта установленная сборка: header показывает
**WEB a41c4e64 / API a41c4e64**, без mismatch. В неопубликованном графе проверены
явная вставка sleep, ELK, редактор связи, разрыв и Undo:3nodes/2edges восстановлены.
Validate вернул parameter verification/contract1.0 для actual graph hash
`7439780d8f3fb5afd51e0765a51d4a0a8ed51e0e3524b04d7a89b8272d8c4fea`.
Console errors/warnings0. [Настоящий screenshot](assets/viewer-input/installed-studio-a41c4e6.jpg).
Viewport override и synthetic browser response injection не применялись.

Новое dismissible input notice проверено React regression, **не отдельным
браузерным malformed-input canary**: реальный UI отправляет корректный protocol.
Не следует читать screenshot Studio как screenshot этого уведомления.
При небольшой высоте окна fit-all уменьшает подписи узлов; рабочая проверка
шага требует zoom/focus, панели параметров имеют собственную прокрутку.
Эта конечная проверка не заменяет полную визуальную приёмку сложных графов.

## Хранение и последующие приоритеты

После rollout: C: Healthy/OK, свободно36432715776B, available RAM18875826176B;
resource guard findings пуст. Это admission этого запуска, не устранение утечки.
Запущен отдельный **8h metadata-only** disk observer:97samples каждые300s,
report cap8MiB, только free C:, logical/allocated Docker VHDX и pagefile metadata.
Первый sample записан7октября03:02:46Z; окончание ожидается11:02:46Z.
Отчёты private в `.local-pilot`; пользовательские файлы/volumes не меняются.
Full-directory scans, VSS/RAM continuous sampling и process writer attribution
в этом ограниченном observer отсутствуют. Allocated pagefile bytes недоступны
из-за `win32_32`, **не считаются нулём**. Elevated host collector отдельно
не запущен: текущий терминал не administrator.

Product ledger сохраняет **9 accepted /41 open**. Следующие P1: continuous
DOWN/MOVE/UP с privileged injector/owner lease/geometry epoch/local release,
rich recorder с correlated native pixels/XPath и task artifact delivery.
[Continuous design](../2026-10-06/CONTINUOUS-INPUT-INTEGRATION.md) ·
[Связанные требования](../2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md) ·
[Product backlog](../2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json).
Причины storage/RAM growth и Git/NTFS corruption, fleet soak и VPS production-role
admission остаются открыты. Frozen source и предыдущие installed receipts
сохраняют свои даты и версии; этот документ их дополняет.
