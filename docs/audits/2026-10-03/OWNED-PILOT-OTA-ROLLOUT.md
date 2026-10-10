# F33 — адресная доставка 1.2.40 на подключённый pilot

Дата: 3 октября2026, Asia/Yekaterinburg. API `8cd5cf0`, UI `a2c4f02`.
Использован существующий кандидат APK `68155c1`, **1.2.40-dev /10240**.

[Evidence JSON](OWNED-PILOT-OTA-ROLLOUT-EVIDENCE.json) · [Адресный workflow](../../operations/OTA-ADDRESSED-UPDATES.md) · [F32 и исходный drift](VPN-CONTROL-OUTCOMES.md) · [Каноническое состояние](../../operations/CURRENT-STATE.md) · [Реестр](../2026-10-01/WEB-AUDIT-REMEDIATION.md)

## Результат

Удалённый PH028 обновлён10232→10240 одним адресным grant. Затем последовательно
обновлены ещё10 совместимых подключённых устройств. **Всего11 новых установок**:
для каждой получены exact command/hash terminal receipt, installed_version10240
и свежий online heartbeat после receipt. Три ранее обновлённых устройства не
переустанавливались. Итоговый каталог02:19:49UTC: **19 records,14 online,
все14 online сообщают1.2.40-dev**; пять offline остаются вне этой приёмки.

Данные приложения не очищались. Host ADB, ручная переустановка и Windows agent
не использованы: metadata/read-only shell и OTA прошли через APK/server.
Разрешения автоматически сняты после terminal handling. Повторных grant или
автоматических повторов install не было.

Это controlled addressed pilot rollout, а не production release: APK остаётся
debug candidate с planar=true/GPU=false. F33 PARTIAL сохраняется: general verified
artifact manifest и bulk operator workflow ещё не реализованы; normal/global
channel не продвинут. Public frontend и Tuna не изменялись.

## Почему обычная автообнова не предлагалась

Live catalog02:09:39UTC содержал21 запись:

| Platform/flavor | Latest | Где используется |
|---|---|---|
| `android/dev` | 1.2.9-dev /10209 | Обычный `UpdateCheckWorker` |
| `android-canary/dev` | 1.2.40-dev /10240 | Explicit addressed canary/recovery |

Текущий Worker запрашивает `platform=android`, свой flavor и установленный
VERSION_CODE. Endpoint выбирает только exact platform/flavor; если latest_code
не больше установленной версии, отвечает update_available=false. Поэтому
10222/10230/10232/10234 не получают10240 из обычного канала.

На11 старых online устройствах не было active10240 grant. У PH017 сохранялся
старый failed10231/timeout от27сентября; он не являлся запросом10240.
Этот readback объясняет **отсутствие предложения10240 в текущей конфигурации**;
он не утверждает, что все прежние network/download/installer ошибки имели одну
причину. Неактивное/неподключённое Android приложение не получает обновление
через одну только запись нового release на сервере.

## Проверка совместимости до установки

1. Локальный10240: SHA256 сверён с managed release; SDK `aapt2 dump badging`
   подтвердил package `com.sphereplatform.agent.pilot.debug`, version10240/dev.
2. SDK `apksigner verify --print-certs` подтвердил APK signature и certificate
   SHA256 `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`.
3. Для известных baseline10222/10230/10232/10234 повторены badging/signature checks;
   package и signer совпадают с кандидатом.
4. На PH028 и каждом из10 targets APK выполнил read-only `pm path` и
   `sha256sum` установленного base.apk. Path проверен перед формированием команды.
5. Installed APK digest точно совпал с локальным подписанным baseline именно
   сообщённой версии. Это связывает проверенный signer с установленным файлом,
   не опираясь только на имя версии в вебе.
6. Перед каждым grant повторно проверены owned online status, heartbeat<60s,
   неизменённая исходная версия и отсутствие другого active grant.

Это **ручная проверенная цепочка конкретных файлов и устройств**. Она не
подменяется заявлением, что каталог теперь сам проверяет package/flavor/signer
любого загруженного APK. Legacy release registration по-прежнему не предоставляет
такой general manifest; будущая автоматическая promotion должна иметь этот gate.

APK10240: **8465471 bytes**, SHA256
`c612fba1e4a537ab1a0d9951e520bbd4063c3548308a4ebc31b72b59fa735a70`.
Скачивание идёт из managed artifact endpoint с origin текущего Android socket;
global channel и SHA опубликованного managed artifact не менялись.

## Адресные результаты

| Устройство | До | После | Подтверждение |
|---|---|---|---|
| auto-ph-028 | 10232 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-022 | 10222 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-020 | 10222 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-019 | 10230 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-018 | 10234 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-017 | 10230 | 10240 | Completed exact receipt + новый heartbeat; old timeout не replay |
| auto-ph-016 | 10222 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-015 | 10234 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-014 | 10222 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-012 | 10222 | 10240 | Completed exact receipt + новый heartbeat |
| auto-ph-011 | 10232 | 10240 | Completed exact receipt + новый heartbeat; local control |

PH028: intent02:13:43.219UTC, completed02:13:48.324UTC, subsequent heartbeat
подтверждён02:15:19.047UTC. Следующая последовательная волна:
**02:18:07–02:19:49UTC**. Полные command IDs, receipts/даты и digest checks
сохранены в evidence; намерение фиксировалось до каждого POST.

Первый PH028 harness пытался DELETE после завершения и получил409:
terminal handler уже снял grant. Отдельный GET подтвердил отсутствие grant,
exact retained receipt и новый heartbeat. Install/grant повторно не создавались.
Это ошибочное предположение cleanup runner, не failed OTA. Исправленный wave
runner проверяет автоматическое снятие, без лишнего DELETE.

## Конечное наблюдение после доставки

12 readbacks с интервалом15s, **02:20:43–02:23:29UTC**: все14 online сообщали10240,
тот же online cohort и heartbeat<60s. Точные максимальные ages и connection epoch
сверки находятся в evidence. Первоначальный observer читал отсутствующее поле
`connected_at`; этот false verification flag сохранён. Отдельные снимки проверяют
настоящий `connected_since` до/после наблюдения, без выдуманного uptime.

Это короткое конечное наблюдение, **не SLA/длительный soak**, не подтверждение
всех физических эмуляторов и не FPS/input-latency/stream+scripts benchmark.
Ранее записанный14→11→12 drift и watchdog старого PH02810232 не переписаны.

## CI и следующие gates

Source/document head **6d5f280** завершил все три CI workflows успешно:
frontend, Android, backend **2351 passed /16 skipped**; static/schema,
production image/RLS/security и Redis acceptance также passed.
Локально:103suites/916 Node24 frontend tests и159 immutable-image VPN regressions.
Новый documentation commit имеет собственные checks, предыдущий success
не объявляется его результатом.

Остаются general artifact manifest/promotion, устойчивое future automatic OTA,
offline-device recovery, fault/soak/clone/Android14+, browser visual acceptance и
F34–F36 single-stream/matrix/XPath. PR19 draft; normal/dev10209 остаётся явно
записанным ограничением, а не скрытым обещанием будущего автоматического обновления.
