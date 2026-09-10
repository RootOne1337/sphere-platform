# Фоновая регистрация APK и запуск связи

**10 сентября 2026 · AUD-75 · проверено в JVM, аппаратный rollout не выполнен.**

[APK guide](../android-agent.md) · [Резервные адреса](ANDROID-SAVED-ROUTES.md) ·
[Готовность системы](../operations/READINESS.md) · [Аудит](../audits/2026-09-05/AUDIT-REPORT.md)

## Что изменилось для оператора

APK с локальной конфигурацией и ключом регистрации теперь проходит регистрацию
в обоих фоновых workers. Наличие ключа больше не переводит его молча в режим
статического токена. Запрос запуска сервиса следует после сохранения назначенного
сервером UUID и credentials. GitHub discovery не требуется, если локальный файл
или MDM уже предоставил адрес и ключ. Доступность самого сервера по-прежнему нужна.

До исправления generated JSON мог дать строку `"null"` вместо отсутствующего ID,
флаг `features.auto_register` не читался из файла, а worker сохранял enrollment key
как рабочий токен. Периодический worker запускал сервис ещё до регистрации.
Сервис запоминал ранний локальный ID на всё время своего reconnect loop — даже
успешная поздняя регистрация не заменяла ID в URL следующих подключений.

## Правила выбора и восстановления

| Состояние | Действие |
| --- | --- |
| Сохранены непустой token и валидный device UUID | Повторить запрос запуска сервиса и watchdog; не регистрировать заново из-за пропавшего marker или предыдущего отказа запуска |
| `auto_register=true` либо в конфигурации нет валидного UUID | Передать supplied `api_key`/`enrollment_api_key` в registration; лишь при отсутствии ключа запросить public config |
| `auto_register=false`, явно указан UUID и непустой ключ | Сохранить legacy static credentials и маршруты; это не проверка серверных полномочий ключа |
| Нет config/key или registration дал 408/429/5xx/network error | Одноразовый worker возвращает retry; периодический завершает текущий тик, оставляя следующую попытку, без нового enrollment marker |
| Registration дал иной 4xx | Одноразовая работа завершается failure; периодический worker сможет повторить на следующем тике. Bootstrap key не становится запасным session token |
| Сервис отклонил запрос запуска после registration | Credentials остаются; следующая попытка повторяет запуск, не HTTP registration |

`AutoEnrollmentWorker` и `KeepAliveWorker` разделяют mutex singleton
`AuthTokenStore`. После ожидания worker повторно читает identity: два фоновых
запуска не выполняют конкурентную registration rotation для одного процесса.
Отмена ожидающего worker не отменяет владельца; отмена discovery выходит наружу,
а не превращается в успешный результат. Это не межпроцессная блокировка и не
сериализация ручного SetupActivity с workers.

WS больше не получает ID один раз от `DeviceInfoProvider` при создании сервиса.
Каждая попытка читает текущий сохранённый UUID. Пока его нет, socket не создаётся.
На `auth_ok` проверяются ID попытки, текущий ID в store и revision маршрута;
ответ старой identity не делает новое устройство connected.

Ранний запуск сервиса другими boot/root путями этим fix не запрещён. После
появления identity уже запущенный loop использует её на следующей попытке;
немедленного enrollment→reconnect сигнала не добавлено. Существующая auth delay
10 s, backoff, network и Android scheduling влияют на время возврата. Periodic
work запрошен с минимальным интервалом 15 минут; это не обещание точного срока.

## Доказательства и повторный запуск

- На `334b3e7`: [8 новых cases, 7 failures / 1 control](../audits/2026-09-05/evidence/android-background-enrollment-before.txt).
- После первого частичного исправления: [12 cases, 4 failures / 8 controls](../audits/2026-09-05/evidence/android-background-enrollment-races-before.txt).
  Это отдельная промежуточная рабочая копия, а не результат исходной ревизии.
- До изменения WS identity: [оба новых сценария падают](../audits/2026-09-05/evidence/android-enrollment-identity-before.txt).

`BackgroundEnrollmentTest` содержит 22 cases с настоящими workers, parser,
registration client и token store. OkHttp application interceptor отвечает внутри
процесса; память preferences и Android service/root/watchdog заменены doubles.
Конкурентные сценарии удерживают registration на явном coroutine gate.
`SavedRouteFailoverTest` добавляет две проверки поздней identity и устаревшего ACK.
Тест раннего boot ускоряет следующую попытку явным force reconnect; он не измеряет
естественную задержку после enrollment.

```powershell
cd android
.\gradlew.bat --no-daemon :app:testEnterpriseDebugUnitTest
```

Итог: [450 tests / 33 suites](../audits/2026-09-05/evidence/android-background-enrollment-summary.json),
[полный вывод](../audits/2026-09-05/evidence/android-background-enrollment-after.txt).
SQL contract tests предыдущих этапов не выдаются за установленный APK→SQL smoke.

## Остаточные риски и следующий этап

Registration использует blocking HTTP; потеря ответа после server commit и
долговечная атомарная запись UUID/tokens/marker ещё не закрыты. Mutex workers
не решает конкуренцию с ручной регистрацией или остановку процесса посреди записи.
Смена identity уже после подтверждения активного WS не имеет отдельного немедленного
сигнала закрытия этим изменением. Наследуемые ошибочные данные требуют диагностики.

Возврат из Android start API означает принятый запрос, а не работающий сервис или
connected WS. Force-stop, reboot, permissions, Direct Boot, OEM, root/non-root и
реальные sockets требуют аппаратных проверок. CPU/RAM/APK size, battery, command
latency и одновременный возврат сотен/тысяч устройств не измерены.

Новой миграции нет. Сначала все backend endpoints должны поддерживать существующие
device refresh и `auth_ok`, затем APK обновляется с прежней подписью и app data.
Переустановка, очистка identity, merge и deployment не являются частью этого fix.
