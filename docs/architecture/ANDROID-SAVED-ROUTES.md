# Сохранённые маршруты Android: основной и резервный

**AUD-74 · 10 сентября 2026 · реализовано в audit branch; физический парк ещё не проверен.**

[Главная](../../README.md) · [APK](../android-agent.md) · [Discovery](ANDROID-DISCOVERY-RECOVERY.md) ·
[WS authentication](ANDROID-CONNECTION-PROTOCOL.md) · [Refresh recovery](../security/device-refresh-recovery.md) ·
[Incident runbook](../runbooks/04-fleet-offline.md)

## Что восстанавливается

APK сохраняет основной и резервный HTTP(S) адрес **одной установки Sphere**.
После неуспешной попытки соединения он выбирает следующий сохранённый маршрут.
Через этот же адрес выполняется refresh, если access token требует обновления.
GitHub и любой config endpoint не нужны для перебора уже сохранённых маршрутов.
Device ID, credentials, refresh operation ID и журнал заданий при переключении
не удаляются; новая регистрация не запускается.

Второй URL должен вести к той же identity/task системе: общие PostgreSQL,
согласованные Redis/WS workers и ключи выдачи/проверки токенов. Второй ingress к
одному backend переживает отказ маршрута, но не отказ самого backend/БД/хоста.
Здесь реализован второй **маршрут управления**, не независимый протокол доставки,
кластер БД или второй исполнитель задания.

## Как настроить

Для уже зарегистрированного APK заполните [route-only template](../../agent-config/templates/lan-routes.json)
реальными адресами своей установки:

```json
{
  "server_url": "https://sphere-primary.example.internal",
  "fallback_server_url": "https://sphere-secondary.example.internal"
}
```

| Способ | Настройка и момент применения |
| --- | --- |
| Android Enterprise MDM | `sphere_server_url` и `sphere_fallback_server_url`; перечитываются при запуске agent service |
| Локальный JSON | `sphere-agent-config.json` в существующих shared/app external/internal search paths; перечитывается при запуске agent service |
| HTTP config | `server_url` и опциональный `fallback_server_url`; сохраняются watchdog после валидного ответа |
| Backend config | Поле `fallback_server_url` в `agent-config/environments/<env>.json`, выдаваемое `/api/v1/config/agent` с существующим Redis TTL |
| Fleet generator | Передаёт fallback из environment в файл устройства; APK принимает `api_key` и `enrollment_api_key` для первичного provisioning |

Route-only MDM/файл для **уже зарегистрированного** устройства не требует копировать
в него enrollment key. Он меняет кандидатов подключения, а не identity. При первой
регистрации по локальному файлу ключ по-прежнему нужен (`api_key`, либо
`enrollment_api_key`); для MDM — `sphere_api_key`. Если оба JSON-ключа заполнены,
явный `api_key` имеет приоритет. MDM имеет приоритет над локальным файлом.
Наличие файла не означает доступ к нему на каждой версии Android: scoped storage
и MDM deployment проверяются на целевых устройствах отдельно.

Файл route-only не является полным bootstrap-config по `agent-config/schema.json`:
тот требует version/enrollment key. Не подставляйте этот template в генератор вместо
environment config. Схема environment дополнена optional fallback; существующий
генератор выполняет только базовую валидацию, не полную JSON Schema validation.

После сохранения route-only настроек перезапустите сервис агента штатным способом
с сохранением app data. Hot reload локального файла/MDM push без рестарта пока нет.
Enterprise `SPHERE_CONFIG_URL` может оставаться пустым, если пара адресов уже
получена локально. Dev по умолчанию продолжает опрашивать свой GitHub config URL;
это не мешает использовать уже сохранённый резерв при отсутствии discovery.

Сеть должна разрешать Android HTTPS к обоим адресам. Действующие cleartext/TLS
правила flavor не ослаблены; произвольный LAN HTTP не становится автоматически
доступным. Не меняйте `server_url` на другое приложение или независимую установку:
агент отправляет credentials на оператором заданные management routes.

## Выбор и подтверждение адреса

Хранятся три значения: последний выбранный адрес (`server_url`), основной кандидат
(`primary_server_url`) и optional резерв (`fallback_server_url`). Список попыток
содержит максимум три уникальных адреса: выбранный, основной, резерв. Третий возможен
при обновлении discovery: прежний рабочий адрес сохраняется до проверки новых.

1. При старте первой пробуется последняя выбранная точка.
2. После network/protocol/auth failure выбирается следующий адрес списка, с
   действующими backoff/jitter/circuit policies. Auth denial сохраняет существующий
   механизм сброса expiry access token и обновления credentials.
3. Refresh использует адрес этой попытки, а не прежний глобальный URL.
   При неизвестном исходе повторяет сохранённый `X-Refresh-Request-Id`; backend
   возвращает того же нерасходованного преемника по контракту AUD-69/70.
4. WebSocket открывается на том же маршруте. До правильного `auth_ok` для device ID
   команды/результаты не передаются и выбранный URL не меняется.
5. После ACK URL обновляется **до** `onConnected` и повторной доставки журнала.
   Проверяется revision маршрутов: поздний ACK старой конфигурации не применяется.
6. Чистое закрытие повторяет последний выбранный маршрут после обычной задержки.
   Автоматического возврата с работающего резерва на основной по таймеру нет.

```mermaid
sequenceDiagram
    participant A as APK
    participant P as Основной маршрут
    participant R as Резерв той же установки
    participant S as Общее durable state
    A->>P: Refresh / WS attempt
    P--xA: Отказ или потеря ответа
    Note over A: Backoff; identity и retry ID сохраняются
    A->>R: Refresh с тем же operation ID, если нужен
    R->>S: Recover/rotate credentials
    R-->>A: Access token + recoverable successor
    A->>R: WS token
    R-->>A: auth_ok для этого device ID
    A->>A: Выбранный URL = резерв
    Note over A,R: onConnected; журнал и команды по прежнему протоколу
```

Discovery сохраняет **кандидатов**. Оно не меняет выбранный URL и не разрывает
авторизованный рабочий WS. Offline агент получает wake-up, чтобы попробовать
обновлённый список. Если fallback отсутствует/равен null в старом HTTP config,
прежний резерв сохраняется. Для удаления резерва явное provisioning пары без него
заменяет старую пару; одинаковые primary/fallback нормализуются до одного адреса.
Неподходящий формат любого URL отклоняет обновление целиком.

Legacy `saveServerUrl` задаёт один адрес и очищает резерв предыдущей конфигурации.
Его по-прежнему используют ручной legacy setup и команда `UPDATE_CONFIG` с
`server_url`. Эта команда пока не поддерживает новую пару: для её настройки
используйте перечисленные выше MDM/JSON/discovery пути. Расширение command contract
и его runtime-проверка остаются отдельной работой.

После успешной регистрации сохраняется адрес, **через который она прошла**.
Отличающийся `server_url` из backend response становится резервным кандидатом,
если оператор не передал явный fallback. Это устраняет замену рабочего LAN route
на недоступный устройству canonical/public URL. Ответ регистрации не является
доказательством доступности рекламируемого адреса.

## Persistence, HTTP и ресурсы

Пара кандидатов сохраняется одним `SharedPreferences.commit()` до её публикации
watchdog. Если commit возвращает false, прежние значения восстанавливаются в памяти,
обновление не подтверждается. Реальные keystore/disk stalls остаются вне HTTP budget.
Подтверждённый active URL сохраняется через прежний `apply()`: при потере этой
последней записи после process death агент может начать с основного, но durable
пара позволяет снова перейти на резерв. Это отдельно проверено с раздельными
memory/disk preferences doubles, не физическим отключением питания телефона.

На каждую попытку приходится не более одного refresh (его HTTP budget 10 s) и
одного WS handshake (20 s). Backoff, очередь refresh mutex, disk/OS scheduling
добавляют время; общего SLO восстановления из этих чисел не следует. Одновременно
не создаются два авторизованных WS или второе выполнение задания.

Management HTTP/WS использует derived OkHttp clients с общими connection pool и
dispatcher, а не отдельный pool/thread executor для каждого адреса. Для registration,
refresh и WS запрещён follow redirect: нужен прямой endpoint, чтобы credentials
не уходили на redirect target. Если shared client уже имеет installation pins,
они применяются и к выбранному резервному hostname. Тест проверяет этот перенос
и сохранение pool/dispatcher; это не проверка реальной TLS handshake. Пины, которые
вообще не загрузились при первоначальном создании shared client, этим изменением
не появляются; отдельный аудит TLS/bootstrap policy остаётся открытым.

## Проверки и rollout

Первый набор на `9ead4f2`: [5 Android failures / 1 control](../audits/2026-09-05/evidence/android-saved-routes-before.txt),
[1 SQL/API failure / 1 control](../audits/2026-09-05/evidence/backend-saved-routes-before.txt).
Отдельно воспроизведены [потеря fallback генератором](../audits/2026-09-05/evidence/config-generator-routes-before.txt)
и [непринимаемый APK enrollment-key формат](../audits/2026-09-05/evidence/android-generated-config-before.txt).
`SavedRouteFailoverTest` покрывает rotation, expired/static credentials, generation,
неверный ACK, stop, сохранение/потерю active apply, failed commit, MDM/файл,
normalization, installation pins и callback ordering.

Итоговый [Gradle run](../audits/2026-09-05/evidence/android-saved-routes-after.txt):
[426 tests / 32 suites](../audits/2026-09-05/evidence/android-saved-routes-summary.json),
включая 27 новых route cases, без failures/errors/skips. Полный
[Python run](../audits/2026-09-05/evidence/saved-routes-combined-suite.txt):
1390 passed / 69,38%; новые пять cases включают три PostgreSQL/ASGI и два generator.

SQL/ASGI проверка использует два synthetic origin одного приложения: ответ после
SQL commit теряется на primary, secondary восстанавливает тот же refresh child;
чужой device ID с новым access token отклоняется. Это не две реальные backend
машины, DNS/VPN или сетевой failover. APK/OS/performance для сотен/тысяч устройств
и наблюдаемое время возврата ещё должны быть измерены.

Для AUD-74 новой миграции нет. Сначала все маршруты backend должны поддерживать
`auth_ok` и recovery-протокол, затем APK обновляется с прежней signing identity и
app data. Optional config field совместим со старыми clients; старый APK его
игнорирует и не получает эту возможность переключения. При rollback APK остаётся
на последнем выбранном `server_url`, но перестаёт использовать сохранённую пару.
Ни service rollout, ни production migration, ни merge этим изменением не выполнялись.

Открыты: durable version/rollback config, проверка принадлежности installation до
передачи credentials, live local config reload, initial enrollment response-loss,
реальные OS/network/Redis/PostgreSQL drills, latency/capacity и incident timeline.
Signed/versioned discovery и отдельный backup transport пока не добавляются.

## Первичный запуск и identity после AUD-75

Сохранённые маршруты не заменяют enrollment. Теперь фоновые workers обменивают
bootstrap key на назначенный ID/credentials до запроса activation, а уже запущенный
WS loop перечитывает ID на каждой попытке. Параллельные workers не делают повторную
registration rotation после успешного владельца. Поздний ACK старого ID отклоняется.
[Отдельный контракт, 24 новых regressions и остаточные ограничения](ANDROID-BACKGROUND-ENROLLMENT.md).
