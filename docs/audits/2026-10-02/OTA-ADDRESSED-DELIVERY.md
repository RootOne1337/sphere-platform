# F33, часть1: доставка OTA на уже подключённое устройство

**Срез:** 2 октября 2026,18:13 UTC+5.<br />
**Установлено:** UI `d61ab49`, backend `8267b94`, [3015/updates](http://127.0.0.1:3015/updates).<br />
**Статус F33:** PARTIAL;30/41 source findings исправлены полностью,11 остаются открытыми.

[Операторский контракт](../../operations/OTA-ADDRESSED-UPDATES.md) ·
[Evidence JSON](OTA-ADDRESSED-DELIVERY-EVIDENCE.json) ·
[Реестр F01–F41](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Каноническое состояние](../../operations/CURRENT-STATE.md)

## Две подтверждённые причины недоставки

1. На preflight обычный `android/dev` latest —1.2.9-dev/10209, а новый10240
   опубликован только в `android-canary/dev`. Android UpdateCheckWorker читает
   `platform=android`. Поэтому обычная проверка не предлагает canary10240.
   Это объясняет несовпадение канала; не все возможные install/transport failures.
2. Старый POST recovery сохранял grant и возвращал201, но не отправлял команду
   уже работающему socket. Передача grant была в reconnect paths. Устройство с
   устойчивым соединением ждало следующего reconnect, хотя API выглядел успешным.

Before source `452eb9e`:13 новых backend assertions failed,0 errors;
13 новых UI assertions failed,0 runtime-error suites. Эти проверки воспроизводят
конкретные отсутствующие контракты, а не доказывают причину всех прошлых обрывов.
Frozen audit `1354d66`/документ `80fb365` сохранены без переписывания.

## Исправления

- `8267b94`: commit→bounded wake→signed SQL re-read→session-fenced OTA send.
  Tenant/RLS/org/agent type, command identity, revoke/replace и expiry проверяются
  на worker. Redis недоступность сохраняет reconnect grant. Live signal не
  становится installation receipt. Authorization tag исключён из HTTP201.
- Добавлен POST `/updates/recovery/{device_id}/dispatch`: тот же ID/deadline;
  absent/expired/tampered/mismatched grant даёт409, чужая/неактивная цель404.
- DELETE имеет optional command ID precondition; UI всегда передаёт его.
  GET показывает actual active/expired/invalid и aware observed time.
- `d61ab49`: paginated target picker, проверенные card/status owners, explicit
  artifact compatibility acknowledgement, TTL, same-ID redispatch, revoke
  confirmation/history, session retirement и отказ от blind write retry.
- Реальный результат показывается только при совпадении receipt/hash/version
  и последующем fresh device heartbeat. Viewer читает; `super_admin` управляет.

## Проверки и их область

| Проверка | Результат |
| --- | --- |
| Backend before |13 assertion failures /0 errors на старом source |
| Backend after |310 passed:91 related OTA cases +219 WS regressions |
| New backend coverage |20 новых mock/API/transport regressions; before доказаны13 initial cases |
| Actual PostgreSQL/RLS/Redis |5 новых cases passed; отдельно внутри immutable backend image тоже5 passed |
| UI before |13 failed /0 runtime-error suites; дополнительные6 cases after-only |
| Focused UI |28 passed:19 новых workflow cases +9 прежних catalog/ownership |
| Full UI |99 suites /825 tests;243 новых frontend regressions сверх582 |
| Static | TypeScript passed; mypy224 source files passed; production Ruff0.15.2 passed |
| Compile | Обе immutable Git archive Linux Docker production builds passed |
| Generated API |173 HTTP operations /136 paths, schema regenerated with production dependencies |
| Actual UI contract logic |19 настоящих recovery responses приняты строгим parser;3 matching installed/heartbeat,15 none,1 другой APK |
| Browser layout/screenshots | OPEN_URL_POLICY_BLOCKED; API/JSDOM/build не выданы за визуальную приёмку |

Actual database tests используют disposable audit PostgreSQL, non-owner runtime
role/RLS и настоящий Redis. Проверены межworker signal, SQL row lock на двух
connections, revoke-before-resend, foreign tenant isolation и viewer403.
Fake WebSocket подтверждает payload/ownership; настоящий Android проверен отдельно.

Harness corrections исключены из before/after proof: missing synthetic JWT,
неверный Jest cwd, неполные read-only lint mounts и unwritable mypy cache.
Mypy повторён с `/tmp` cache; полный lint с scripts/config mounts passed.
Первая artifact preflight попытка без agent Authorization получила ожидаемый401
до любых grant writes; байты затем сверены read-only в managed storage и локальном
artifact. Вспомогательный Node harness исправил собственное имя `exports`.
Эти ошибки инструментов не объявляются дефектами приложения или успешными тестами.

## Реальный remote canary PH013

**Операторская классификация сети:** удалённый эмулятор; не geolocation proof.
Перед выдачей: online/active10230, no active grant. Managed artifact10240 и локальный
APK имеют8465471 bytes и одинаковый SHA256
`c612fba1e4a537ab1a0d9951e520bbd4063c3548308a4ebc31b72b59fa735a70`.
Существующий receipt подтверждает package `com.sphereplatform.agent.pilot.debug`
и pilot baseline signer. Remote installed certificate не запрашивался; Android
PackageManager сам проверил совместимость при update. Сервер не получил новый
verified artifact manifest.

| UTC2 октября | Подтверждённое событие |
| --- | --- |
|13:11:37.922312 | `ota_recovery.live_send_attempt`, sent=true, command `fe0b73bf-9e42-4b93-ac1d-261f59b6db06` |
|13:11:58.819523 | После замены процесса recovery socket повторно передал тот же ID |
|13:11:59.247893 | Persisted completed, installed10240, recovered_after_process_restart=true |
|13:12:00.358887 | Первый принятый post-result heartbeat10240 |
|13:13:00.685197 | Дополнительный fresh heartbeat10240, online |

**Один POST grant**,600s, один APK/target. Replay новой команды не создавался;
same-ID reconnect — существующий durable Android recovery/journal path.
HTTP201/wake и final result разнесены. Данные APK не очищались; manual install,
ADB/PC Agent, reboot или arbitrary script commands для этой проверки не нужны.

Каталог18:13:39 UTC+5:19 records/14online/5offline;3online10240,2online10230,
5online10222,2online10232,2online10234. Это конечный срез, не24h SLA.
Normal `android/dev` latest10209, global/latest aliases не менялись; debugcanary
не выдаётся за подписанный production release. Нового APK этим batch не собрано.

## Установка и сохранённые соседи

- Backend image `sha256:763a4666d5c63961b3f5b9bf538899f700ff766eea270fdab244e871da424eb4`,
  readiness и source8267b94 подтверждены13:07:29 UTC.
- Review UI image `sha256:70e86bc679d47a73d3060b5b7adb7ae41ff95587c66a8171218456f11dde9b01`,
  source d61ab49; UI/gateway healthy13:08:46 UTC. Listener loopback3015,
  read-only roots, capability drop и restart policy сохранены.
- Login, same-origin API, actual compiled stamp/static asset, unauthorized
  observability401, Prometheus target up, Grafana session/health и events
  snapshot/pong passed13:09:25 UTC.
- 43 других контейнера сохранили IDs/images/StartedAt/running. Public UI,
  APK artifact storage и tunnels не заменялись. Old images/overlays сохранены
  для rollback; rollback переставляет image, а не отменяет уже завершённый update.

## Что остаётся открытым

F33 остаётся PARTIAL: bulk rollout orchestration, verified artifact package/flavor/
signer manifest и production signing не реализованы этой частью. Нормальный OTA
канал требует осознанного promotion после gates. Пять offline devices не обновлены
и причины их offline этим trial не определены.

Нет нового video/FPS/input latency trial, fresh browser walkthrough,20–30-device
soak/rollout или cold-host/clone acceptance. Старые APK replay warnings сохраняются
в отдельной исторической диагностике; неизвестные receipts не ACKаются вслепую.
N01 Android artifact upload, N03 legacy RPC UX, F26/F27/F28/F32/F34/F35/F36/F39/F40/F41,
durable audit outbox и остальные исходные gates не объявлены решёнными.

Exact-head GitHub CI нового documentation commit фиксируется отдельно в PR #19;
green CI предыдущего452eb9e не подменяет проверки нового head.
