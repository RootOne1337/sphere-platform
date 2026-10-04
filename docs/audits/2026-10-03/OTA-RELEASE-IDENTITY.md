# F33 — публикация OTA, совместимость APK и установка 1.2.41

Дата: 3 октября 2026, Asia/Yekaterinburg. Последний API/UI readback:
**2026-10-03T03:17:58.138904+00:00**. API `facba9a4b56f9b121f028bc371d24b94a08364de`, UI `77fca37847590bef526ae5becdf7b1986d5b15ea`.

[Evidence JSON](OTA-RELEASE-IDENTITY-EVIDENCE.json) · [Операторский контракт](../../operations/OTA-PUBLICATION-AND-APK-CHECKS.md) · [Адресная доставка](../../operations/OTA-ADDRESSED-UPDATES.md) · [Current State](../../operations/CURRENT-STATE.md) · [Реестр F01–F41](../2026-10-01/WEB-AUDIT-REMEDIATION.md)

## Результат и граница приёмки

Кандидат **1.2.41-dev /10241** опубликован в `android-canary/dev`. Сначала
подтверждился PH028, затем последовательно ещё 13 подключённых устройств.
**14 из 14 установок имеют exact command/hash/version terminal receipt и новый
heartbeat после него.** Grant автоматически снят у каждой цели. Каталог содержит
19 устройств: 14 online на 10241 и 5 offline вне этой приёмки. Повторных install
POST, очистки данных или host ADB не было.

12 read-only срезов **03:14:44–03:16:35 UTC** сохранили тот же online cohort и
сообщённые `connected_since`; максимальный возраст heartbeat **29.886s**.
Наблюдение конечное: оно не подтверждает длительный soak, SLA или плавность видео.
API был намеренно заменён до волны, поэтому прежние connection epochs10240 не
сравниваются с новыми как непрерывная связь через deploy.

**F33 остаётся PARTIAL.** Принята конкретная адресная волна pilot. Generic
verified artifact manifest, upload UI, bulk operator workflow, normal promotion
и production stable signer пока OPEN. Public frontend и Tuna сохранены.

Дополнительный read-only срез **2026-10-03T03:31:16.217239+00:00** через
**991.407s** после первого наблюдения: те же 14 online,
все 10241, совпадающие reported epochs, heartbeat максимум
**29.031s**. Каталог 22 entries; normal/dev10209,
canary/dev10241. Это два разделённых во времени readback, не непрерывный uptime SLA.

## Что было доказано до исправления

1. Backend принимал malformed release metadata: boolean/string versionCode,
   неподдерживаемые каналы, некорректную SHA/URL и неизвестные поля. Повтор того
   же номера версии в активном канале также принимался. На предыдущем source
   регрессионный набор дал 18 failures / 2 passed; два failures относятся к новому
   контракту выбора неоднозначного latest, остальные к input/duplicate behavior.
2. Android проверял SHA скачанного файла, но не его package/version/SDK/signer
   перед границей installer. Синтетический non-APK с правильной SHA доходил до
   подменённого installer boundary. Это доказательство отсутствия guard, а не
   выполненной установки чужого APK на реальный Android.
3. Старый create modal использовал alert и browser `type=url`, который не
   принимал поддерживаемый managed-путь. Неточный/потерянный ответ не имел
   отдельного read-only reconciliation. Новая форма проверяется JSDOM, без
   утверждения о визуальной приёмке.
4. Причина отсутствия обычного предложения OTA остаётся подтверждённой
   конфигурацией канала: Worker запрашивает `android/dev`, latest там 10209;
   новые APK опубликованы в `android-canary/dev`. [Предыдущий channel readback](OWNED-PILOT-OTA-ROLLOUT.md)
   сохраняет дату и исходную 10240 волну. Ни одна запись каталога сама по себе не
   запускает/восстанавливает offline Android.

## Изменения и атомарные commits

| Commit | Изменение | Проверка |
|---|---|---|
| `73bfa9a` | Strict metadata, ограниченные строки/URL, duplicate 409 под межпроцессным FileLock, conflicting latest 503 |25 cases, включая два процесса |
| `77fca37` | Validated publication modal, сбрасываемое подтверждение, exact201 receipt, retained unknown, GET reconciliation |104 suites/946 frontend tests |
| `facba9a` | APK package/version/minSdk/current signer guard; bounded failure codes;10241 |818 passed / 1 skip на каждый flavor |
| `5bb36ca` | Сгенерированный OpenAPI совпадает с новым HTTP контрактом |175 operations/137paths; networknone exporter check |

Source: [router](../../../backend/api/v1/updates/router.py),
[create dialog](../../../frontend/src/features/updates/CreateReleaseDialog.tsx),
[receipt checks](../../../frontend/src/features/updates/releasePublication.ts),
[APK verifier](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaApkVerifier.kt).
Публикация внешнего HTTPS URL не скачивает и не проверяет его APK. Уникальность
касается активного каталога: delete/republication пока не является immutable history.

## Проверка самого APK

| Поле | Значение |
|---|---|
| Source |`facba9a4b56f9b121f028bc371d24b94a08364de`|
| Package |`com.sphereplatform.agent.pilot.debug`|
| Version |`1.2.41-dev /10241`|
| Размер |8467827 bytes|
| SHA-256 |`5222d948a1a9f81e575955cc300f24dba41296b88d4993ef8acb033c323c6532`|
| Certificate SHA-256 |`3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`|
| Discovery |Подписанный manifest 27; baked management URLs пустые|
| Video profile |planar=true/GPU=false, debug probe retained|
| Build |`2026-10-03T03:02:00.016881+00:00`; apksigner v2 и aapt metadata passed|

На каждой цели read-only `pm path`/`sha256sum` связали установленный файл 10240
с локальным baseline, проверенным `apksigner`/`aapt`. Только после совпадения
package и signer выдан адресный grant 600s. SHA baseline:
`c612fba1e4a537ab1a0d9951e520bbd4063c3548308a4ebc31b72b59fa735a70`.
Всего 28 read-only Android commands и 14 адресных обновлений, без Windows agent.
Intent сохранялся до POST; uncertain outcome остановил бы оставшуюся волну.

Новый native guard проверяется на Android 26 и 28 в Robolectric и стоит перед
обоими installer paths. Он требует строго новую версию и точный набор текущих
сертификатов, намеренно отвергая key rotation. **Живой переход10240→10241
исполнял installer 10240. Новый guard 10241 ещё требует live canary следующего
совместимого обновления**; эти receipts не подменяют такую проверку.

Private build metadata `installed=false/published_to_ota=false` сохраняет
состояние на момент сборки. Subsequent publication/install outcomes записаны
отдельными датированными receipts, а не переписаны в build snapshot.

## Публикация и реальные HTTP отказы

03:02:54 UTC: duplicate 409, unknown field422, boolean version422, invalid
digest422, credential URL422. После пяти отказов прежний21-entry каталог
не изменился; Android commands на этом шаге не отправлялись.13 постоянных
соседних контейнеров сохранили ID/image/StartedAt, включая public UI и туннели.

03:04:55 UTC: managed artifact проверен по hash/size и атомарно помещён в
artifact store. POST 201 и exact GET readback создали одну canary запись
`d2d67dc0-bdd3-4b7e-8d3a-aac89a5ed427`; каталог 22 entries, normal/android unchanged.
Это operator staging конкретного файла, не новый general upload API.

## Подтверждённые установки

Все строки:10240→10241, один POST на устройство, completed, recovered after
process restart, grant autocleared. Даты UTC; полный hash/version в Evidence JSON.

| Устройство | Command ID | Terminal receipt | Новый heartbeat |
|---|---|---|---|
| auto-ph-028 | e9726d9a-09bc-4f64-999b-435e79c4126e | 2026-10-03T03:06:16.550662+00:00 | 2026-10-03T03:06:17.273835Z |
| auto-ph-025 | 5b3db229-8ed3-46ef-9ab5-78a1439c6d00 | 2026-10-03T03:08:23.928861+00:00 | 2026-10-03T03:08:24.674930Z |
| auto-ph-022 | 9f3700e4-e6d9-4bfa-a930-21ea2aefb4c8 | 2026-10-03T03:08:33.979424+00:00 | 2026-10-03T03:08:33.983739Z |
| auto-ph-020 | 887a7ba4-0a08-4ffb-83be-9e0747c6ca77 | 2026-10-03T03:08:45.788573+00:00 | 2026-10-03T03:09:15.765384Z |
| auto-ph-019 | 91df03fd-c26b-49c0-a92d-8555e2e936f3 | 2026-10-03T03:09:24.526578+00:00 | 2026-10-03T03:09:24.531790Z |
| auto-ph-018 | 4c689829-2055-4714-a274-5e9d51e4fa82 | 2026-10-03T03:09:34.540495+00:00 | 2026-10-03T03:09:34.543197Z |
| auto-ph-017 | 736cc302-26ce-4691-b288-6ac6c721d093 | 2026-10-03T03:09:44.728786+00:00 | 2026-10-03T03:10:14.702930Z |
| auto-ph-016 | ec206ddf-cf26-4709-96ba-e9544576805d | 2026-10-03T03:10:21.348192+00:00 | 2026-10-03T03:10:22.093449Z |
| auto-ph-015 | 76d1015d-ac96-46d2-b20a-5bfb450cb716 | 2026-10-03T03:10:30.425538+00:00 | 2026-10-03T03:10:31.174141Z |
| auto-ph-014 | cd9dcb9c-f8d2-48a4-a6c3-bdd21614bda3 | 2026-10-03T03:10:40.320247+00:00 | 2026-10-03T03:10:41.056458Z |
| auto-ph-013 | d38a5690-2487-446e-8045-5f5e9578e03d | 2026-10-03T03:10:51.119290+00:00 | 2026-10-03T03:10:51.124692Z |
| auto-ph-012 | e9987e6a-538d-410b-be69-12e486c390f7 | 2026-10-03T03:11:00.971272+00:00 | 2026-10-03T03:11:00.981362Z |
| auto-ph-011 | cacd29bb-a122-45cf-9866-a1beb455ac35 | 2026-10-03T03:11:12.651944+00:00 | 2026-10-03T03:11:13.937010Z |
| auto-ph-010 | 49cfdca7-ef18-4331-b57e-53a8f342cb64 | 2026-10-03T03:11:23.817330+00:00 | 2026-10-03T03:11:25.187422Z |

Краткий offline при замене процесса виден в canary readback и не скрыт:
03:06:15 PH028 offline, затем completed03:06:16 и heartbeat03:06:17.
Он не учитывается как долгий post-install soak. Пять offline записей каталога
не входят в эти14 installations и не объявлены автоматически исправленными.

## Установленные API/UI и observability

- Review: [3015/updates](http://127.0.0.1:3015/updates), UI `77fca37`;
  container `b842a01b6187ebfe800a797654c3ec5672146206035c1d274e8f6169269b79ed`, image `sha256:264aaa341c32e37153e4c19eff0c3db418cf3b066c834a76d4794b79a704c6fa`.
- API `facba9a`, container `bbf609a90ff89db865ffd5b238864d311a8a89d432ed5e409eeccb361663a694`, image `sha256:9e65ff07fe884391ccf4d67ebc8f83cbcf6d2aecb59f75987e9caf136c927d8a`.
- Login/same-origin API, compiled UI stamp/static asset, Prometheus backendUP,
  Grafana session90s/HttpOnly/SameSiteStrict +databaseOK, events WS auth/snapshot/pong
  подтверждены03:17:58 UTC. Unauthenticated observability401.
- Review UI/gateway read-only, cap-dropALL, restart unless-stopped;3015 только loopback.
- Fresh browser visual/keyboard/mobile: **OPEN_URL_POLICY_BLOCKED**. API и JSDOM
  не названы визуальным доказательством; alternateURL/browser bypass не использован.

## Тесты и воспроизводимость

| Проверка | Фактический результат |
|---|---|
| Backend release identity |До18failed/2passed; после25passed|
| Related backend на disposable PostgreSQL/Redis |130passed|
| Те же tests в immutable shipped API image, без mount backend |130passed/21warnings|
| Mypy shipped dependencies |225 source files passed|
| Полный frontend, Node24.21.0 Linux, networknone |104suites/946passed/0failed/0skip; types/build passed|
| Android DevDebug |819 cases: 818 passed / 0 failed / 0 errors / 1 skipped|
| Android EnterpriseDebug |819 cases: 818 passed / 0 failed / 0 errors / 1 skipped|
| Full GitHub backend на facba9a |2381 passed / 16 skipped; workflow затем failed на staleOpenAPI|
| Exporter после 5bb36ca repair |check passed; 175 operations / 137 paths|

Повторный CI source/schema head **`5bb36caa8663da097738d5ea8b8e339cbee42b2c`** завершился
успешно; срез **2026-10-03T03:32:51.501739+00:00**. Backend повторно 2381 passed / 16 skipped,
generated OpenAPI check passed. Preview workflow success не принят как deploy proof.
Новый documentation-only commit имеет собственные checks; прежний CI не называется
проверкой ещё не созданного head.

| Workflow | Run | Conclusion |
|---|---|---|
| CI — Frontend | [37092694000](https://github.com/RootOne1337/sphere-platform/actions/runs/37092694000) | success |
| CI — Backend | [37092694003](https://github.com/RootOne1337/sphere-platform/actions/runs/37092694003) | success |
| CI — Android | [37092694001](https://github.com/RootOne1337/sphere-platform/actions/runs/37092694001) | success |

Android skip: ConfigRecoveryTest требует непустой baked DEFAULT_SERVER_URL и
DEFAULT_API_KEY; этот signed-discovery pilot намеренно не содержит baked URL.
Поэтому assumptionfalse, а не скрытая неуспешная проверка. Оба build flavors
собраны `--offline --no-daemon --rerun-tasks`. Полные test reports и digest
сырых receipts приведены в JSON. Тесты загрузки/20–30 stream+scripts этим
набором не исполнялись.

Ошибки тестового harness сохранены: Mockk nested-call fixture и неподдерживаемый
Robolectric SDK 35 исправлены до accepted SDK26/28 прогона; старый string422
assert обновлён под стандартный field-validation ответ. Staging path и target
guard corrections остановились до publication/install, потом прошли exact proof.
Это не production acceptance на SDK 35.

## Осталось до закрытия F33 и PR19

1. Verified artifact manifest/package/flavor/signer на стороне публикации,
   general upload UI и immutable publication history.
2. Durable outcome reconciliation после reload/между вкладками и общий bulk workflow.
3. Stable signing/profile, live upgrade from10241 и безопасная normal promotion;
   текущая ordinary автообнова получает10209, а не canary10241.
4. Fresh visual/keyboard/mobile acceptance и длительный soak на согласованном
   составе. Отдельно streamFPS/inputlatency и совместный stream+scripts20–30 devices.
5. F32/F33 PARTIAL, F34–F36/F39–F41, N01/N03 и durable audit outbox остаются OPEN.

Лицензии/авторство frontend references этим OTA batch не менялись.
Контракты Android сверены с официальными
[PackageManager](https://developer.android.com/reference/android/content/pm/PackageManager),
[SigningInfo](https://developer.android.com/reference/android/content/pm/SigningInfo) и
[apksigner](https://developer.android.com/tools/apksigner).
