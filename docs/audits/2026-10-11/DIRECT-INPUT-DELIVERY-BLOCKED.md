# Прямые жесты: подготовленная доставка и фактически установленное состояние

11 октября 2026, UTC+5. Документ отделяет рабочий стенд от проверенного кандидата.
Production, stable 1.3, localhost/LAN/WAN/TURN и задержка картинки не приняты.

## Действующий стенд

На 3015 и действующем туннельном адресе установлены **UI/API `6ee80c1f`**.
Повторно совпали SHA-256 всех 29 полученных JS/CSS assets. PostgreSQL/Redis готовы;
анонимное чтение истории сеансов возвращает401. Это проверка доставки и доступа,
а не подтверждение прямого видео или управления Android.

Фактическая проверка пакетов разделена по версии:

| Версия | Проверенные устройства | Доказательство |
|---|---|---|
| 1.2.54-dev /10254 | PH010 | SHA установленного APK совпал; тот же OTA-command завершён Android после перезапуска процесса |
| 1.2.53-dev /10253 | PH011, PH012, PH014, PH015, PH017, PH018 | Датированная повторная инвентаризация установленного SHA |
| 1.2.52-dev /10252 | PH019, PH025 | Датированная повторная инвентаризация установленного SHA |

Девять текущих проверок пакета, allowlist из15 устройств и историческая OTA
на15 устройств — разные величины. PH030 выключен пользователем и исключён.
Ещё пять устройств были offline. Отсутствие свежей проверки не доказывает
удаление ранее установленного пакета или успешное новое обновление.

[Замороженная текущая квитанция](CURRENT-STREAM-DELIVERY.json).
Первоначальная [установка основного видео](DIRECT-PRIMARY-VIDEO-INSTALLED.json)
сохраняет свой старый scope; её версии и15 устройств не перенесены в новый срез.

## Подготовленный кандидат

- API/UI: `e9af9e60be1b2dcb1f13f7dd8b17db93dc8bfa4c`.
- Android54: `7b6251817f42423a1ae90fb0c8837a8e976b3f60`.
- APK SHA: `a8286157a7f78dd64fd7e954770f076d744822572602f56a154ad40fbad023d0`.
- Размер: 57 688 052 bytes; прежний pilot package и signer сохранены.
- Backend CI38092772393, Frontend CI38092772394 и Android CI38092772408 завершены
  успешно дляe9. APK54 отдельно связан с успешным Android CI38092053110 для7b.
- В обоих локальных Android flavors по1028 unit tests, 0 failures/errors,
  3 skipped; lint и debug assembly завершены. Это не длительная проверка APK на игре.

Реализация добавляет reliable ordered DataChannel `sphere-control-v1` на primary
video peer. DOWN/MOVE/UP/heartbeat и input ACK обходят серверную пересылку.
Авторизация, владение, expiry и CLOSE остаются согласованными с сервером.
Back/Home/Recents/Menu и текст сохраняют прежний серверный API.
[Контракт, границы и приёмка](DIRECT-INPUT-CANDIDATE.md).

## Почему новая API/UI установка не выполнена

Reviewed installer остановился **до `docker image load` и до замены контейнера**.
Его source/image/полный CI/schema/Compose проверки прошли; host preflight получил
`volume_not_ready`. В срезе10 октября23:07:43UTC Windows вернула:

| Измерение | Результат |
|---|---|
| Volume health C: | Warning |
| Volume operational status | Full Repair Needed |
| Свободное место | 35 537 608 704 bytes |
| Доступная RAM | 14 428 950 528 bytes |
| Commit / limit | 65 211 883 520 /101 336 473 600 bytes |

В System log есть новое NTFS98 от10 октября22:35:41UTC, то есть11 октября03:35:41
по местному времени: требуется онлайн-сканирование. Проверка physical disk
показывала Healthy/OK, но это не исключает неисправности накопителя, драйвера,
памяти или ошибки файловой системы. Причина повторного состояния не установлена.
`fsutil dirty query C:` недоступен текущему неадминистративному процессу; dirty bit
не объявляется подтверждённым. Свежего результата CHKDSK пока нет.

Запрошена `chkdsk C: /scan` из PowerShell администратора. Перезагрузка, offline
repair, откат проекта, ослабление host guard, VPN или firewall этим этапом не выполнялись.
После результата scan заново проверяется фактическое состояние тома; старый
результат успешного reboot repair не заменяет этот новый срез.

## Конечная проверка PH010 после OTA54

Браузер показал пакет54, основное изображение по server WebSocket,41 отображённый
кадр, 0 decode/render errors. Home подтверждён Android; контроль вернулся в ready.
Ответ команды572мс, максимальный контрольный RTT184мс в записанном окне.
Эти числа не являются capture-to-display latency.

Прямой канал в этом окне не открылся:0 direct frames, `connection_deadline`,
ICE checking. В Android, после проверки boot identity эмулятора, прочитан последний
native aggregate:237 ICE requests sent,0 responses received,0 succeeded pairs,
DTLS new. Это локализует отказ до рабочего direct transport, но не устанавливает
конкретный firewall/VPN/NAT drop. Исторические1804 прямых кадра PH011 и20/20 echo
ноутбука не доказывают нынешний путь.

## Исправление повторного отказа управления

На6ee зафиксированы два server control events с интервалом около22мс:
сначала retryable `input_temporarily_unavailable/runtime_unavailable`, затем
terminal `input_rejected_or_unavailable`. Второй ответ во время ожидаемого RELEASE
отменял автоматическое восстановление браузера.

Вe9 валидные события прежнего владельца во время его retirement отбрасываются
без input dispatch, ACK и дополнительного terminal error. Неизвестный владелец,
malformed input и новая OPEN остаются отвергнутыми. Касания не повторяются.
Полные WS tests дляe9:635 tests +44 subtests. Это исправленный source/CI,
**ещё не установленное исправление рабочего API**.

## Дополнительная история диагностики в исходниках

В текущем source исправлена подпись маршрута: история отдельно показывает
`control_transport`, вместо постоянного «управление через сервер» при WebRTC-видео.
Для старой записи без маршрута показывается «Маршрут касаний не сообщён».

Автоматический viewer report теперь сохраняет aggregate ICE candidate/pair counts,
requests sent/responses received и относительное время среза текущей попытки.
Отсутствующий packet counter остаётся null. Nested DTO строгий; IP, SDP, candidate
IDs, credentials, ввод и изображения не сохраняются. Используется прежняя cadence;
новых таймеров, getStats вызовов, очередей или автоматических команд нет.
Лимиты10 sessions/device,32KiB/session,7 days и byte eviction сохранены.

647 WS tests +44 subtests и549 frontend stream tests прошли после этих изменений;
TypeScript, scoped ESLint и Ruff прошли. Новая telemetry **тоже ещё не установлена**.
Native ICE/progress aggregates пока читаются отдельно из локального canary log;
их автоматическая привязка к истории сеанса ещё не реализована.

Реестр и441 tracked Markdown согласованы.37 documentation tests +63 subtests
проверяют источник установки, каждый installed package SHA, текущие версии,
отдельную историческую приёмку и невозможность выдать старые прямые кадры за
нынешний маршрут. Generated OpenAPI/endpoint catalog совпадают с приложением.

## Следующие обязательные проверки

1. Результат scan и готовность Windows volume перед runtime replacement.
2. Reviewed API/UI, одинаковые assets на обоих адресах и native54 admission.
3. Реальные direct native DOWN/MOVE/UP/ACK без server input dispatch.
4. Idle/reconnect/lag, held CANCEL, несколько viewers и передача владельца.
5. Адресная OTA остальным совместимым устройствам после принятого canary.
6. Ближайший маршрут localhost/LAN/WAN/VPN/TURN, correlated frame timing и soak.

[Рабочий реестр](../../operations/WORK-STATUS.md) ·
[Аудит надёжности](STREAM-RELIABILITY-AUDIT.md) ·
[Исследование транспорта](../../design/BROWSER-DIRECT-TRANSPORT.md).
