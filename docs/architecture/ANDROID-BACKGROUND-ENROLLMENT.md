# Фоновая регистрация APK и запуск связи

**10 сентября 2026 · AUD-75–77 · проверено в JVM, аппаратный rollout не выполнен.**

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
а не превращается в успешный результат. Это не межпроцессная блокировка. AUD-77 ниже дополнительно сериализует
HTTP registration из SetupActivity и workers с refresh через token mutex.

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

Итог AUD-75: [450 tests / 33 suites](../audits/2026-09-05/evidence/android-background-enrollment-summary.json),
[полный вывод](../audits/2026-09-05/evidence/android-background-enrollment-after.txt).
SQL contract tests предыдущих этапов не выдаются за установленный APK→SQL smoke.

## Остаточные риски и следующий этап

HTTP registration ограничен и отменяется после AUD-76. AUD-77 объединяет запись
UUID/tokens/routes и упорядочивает registration/refresh внутри процесса. Marker
остаётся отдельным: после его потери worker использует сохранённую identity. Потеря
ответа после server commit и реальная смерть процесса/keystore ещё не закрыты.
Смена identity уже после подтверждения активного WS не имеет отдельного немедленного
сигнала закрытия этим изменением. Наследуемые ошибочные данные требуют диагностики.

Возврат из Android start API означает принятый запрос, а не работающий сервис или
connected WS. Force-stop, reboot, permissions, Direct Boot, OEM, root/non-root и
реальные sockets требуют аппаратных проверок. CPU/RAM/APK size, battery, command
latency и одновременный возврат сотен/тысяч устройств не измерены.

Новой миграции нет. Сначала все backend endpoints должны поддерживать существующие
device refresh и `auth_ok`, затем APK обновляется с прежней подписью и app data.
Переустановка, очистка identity, merge и deployment не являются частью этого fix.

## Дедлайн и отмена первичной регистрации (AUD-76)

`DeviceRegistrationClient` больше не удерживает вызывающую coroutine до возвращения
blocking `execute()`. Асинхронный Call получает отдельный timeout 10 s; coroutine
budget охватывает ожидание dispatcher, headers и разбор success body. Отмена caller
отменяет именно этот Call. Общие WS client timeouts, pool и dispatcher не меняются.

Callback закрывает response и возвращает только разобранные значения. Проверка
cancellation предшествует записи store, поэтому body, завершившийся после отмены,
не записывает identity/routes/tokens. Собственный HTTP timeout становится IOException:
одноразовый worker возвращает retry и освобождает enrollment mutex. Внешняя отмена
остаётся CancellationException, а следующий worker может продолжить работу.

Success body ограничен **64 KiB в байтах до JSON parse**, с пробой следующего байта;
внутренний буфер Okio может прочитать ещё один segment. Большой ответ с валидным
JSON-префиксом больше не обрезается до якобы успешной регистрации. При non-2xx
сохраняется HTTP status без ожидания error body; `RegistrationException.responseBody`
остаётся null. Для подробностей ошибки нужен server-side log, не полный response в APK log.

Baseline на `f9cccbc`: [5 failures / 2 controls](../audits/2026-09-05/evidence/android-registration-http-before.txt),
[точные сообщения](../audits/2026-09-05/evidence/android-registration-http-before-summary.json).
Добавлены 13 `RegistrationRecoveryTest` и два `BackgroundEnrollmentTest` cases:
headers/body deadlines, parent cancellation, late reply после новой identity,
граница 64 KiB, error status без body, IO retry, dispatcher cancellation и mutex
release после stop/timeout. Итог:
[465 tests / 34 suites](../audits/2026-09-05/evidence/android-registration-http-summary.json),
[полный вывод](../audits/2026-09-05/evidence/android-registration-http-after.txt).

Первый расширенный candidate имел один [неверный критерий теста очереди](../audits/2026-09-05/evidence/android-registration-http-fixture-before-summary.json):
application interceptor может увидеть отменённый Call после освобождения слота.
Это не сетевой send. Финальная проверка ждёт окончания callbacks и проверяет cancel,
сохранение работающего соседа и отсутствие credential writes; исходный failure сохранён.

**Границы:** срок 10 s не включает ожидание worker mutex, fingerprint/device IO,
планирование Android или уже начатую синхронную запись preferences. AUD-77 ниже
добавляет единый commit и fencing неотменённых ответов. Cancellation не отменяет
начатый disk commit; idempotent receipt initial registration пока отсутствует. Резерв применяется
к уже установленной связи; начальный registration вызов сам не перебирает endpoints.
Реальные sockets/OS/keystore/process death/fleet latency остаются непроверенными.

## Сохранение регистрации и конкурирующие ответы (AUD-77)

Успех `DeviceRegistrationClient.register()` теперь означает `commit(true)` одной
операции: active/primary/fallback, UUID, access/refresh, expiry и удаление старого
refresh intent. Проверяются UUID, непустые строковые credentials и положительный
expiry без переполнения. JSON null/число/boolean не становятся строкой токена.

Registration и refresh используют один coroutine mutex `AuthTokenStore`. Mutex
workers остаётся внешним; ручные HTTP регистрации используют внутренний. Запросы
сериализуются, но не объединяются: два явных вызова могут последовательно выпустить
две пары credentials. Отмена ожидающего не отменяет владельца. Межпроцессной
блокировки нет; 10 s HTTP budget начинается после очереди и metadata IO.

Перед HTTP запоминаются версии credentials и маршрутов. Commit под monitor store
отклоняет ответ, если за это время произошли clear, замена ID/tokens/API key или
изменение маршрутов, включая изменение и возврат прежних значений. Успешная запись
также инвалидирует ранее захваченный WS route plan при неизменном URL. Синхронные
читатели store ждут завершения commit/rollback и не получают промежуточный token.

При `commit(false)` или exception caller получает IOException, а store восстанавливает
полное прежнее состояние памяти, включая отсутствие expiry. Это не rollback на
сервере и не гарантия восстановления физического диска. Если сам rollback также
падает, исходная ошибка содержит suppressed failure; требуется диагностика storage.
Синхронный commit/rollback не имеет deadline и может задержать читателей.
Отмена до commit запрещает запись; отмена во время уже начатого commit его не прерывает.

Baseline `fb6e908`: [9 cases / 8 failures / 1 control](../audits/2026-09-05/evidence/android-registration-state-before-summary.json),
[вывод](../audits/2026-09-05/evidence/android-registration-state-before.txt).
После fix: 20 новых `RegistrationPersistenceTest`, включая отказ/exception записи,
отбрасывание pending apply при пересоздании store, обратный порядок ответов,
clear/ABA/route/ID races, отмену mutex waiter, оба порядка refresh/registration,
invalid payload и запрет публикации неуспешного commit читателю.
[Полный прогон: 485 tests / 35 suites](../audits/2026-09-05/evidence/android-registration-state-summary.json),
[вывод](../audits/2026-09-05/evidence/android-registration-state-after.txt).
Preference disk и transport — контролируемые doubles, не аппаратный crash test.

**Открыто:** сервер может выпустить credentials, которые клиент не сохранит из-за
response loss, cancellation, failed commit или отклонённого stale reply. После
неудачной повторной регистрации прежние credentials могут уже не работать; shortcut
worker с прежним token/UUID сам по себе этого не обнаруживает. Нужен отдельный
протокол восстановления initial enrollment, а не обещание, что локальный rollback
отменил серверную rotation. Legacy static-key setup всё ещё пишет отдельными
операциями. Marker, clone collisions, initial fallback traversal и аппаратные
OS/network/fleet измерения также не закрыты.

Контракт синхронного commit и асинхронного apply сверён с
[Android SharedPreferences.Editor](https://developer.android.com/reference/android/content/SharedPreferences.Editor).
Это основание для модели теста, а не доказательство всех гарантий keystore/OEM.
