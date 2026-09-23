# Локальный стенд для совместного тестирования

**23 сентября 2026 · Windows / Docker Desktop · development, авторизация включена.**

Текущий локальный pilot: backend **`3be0e29`**, frontend **`9924eb1`**, оба локальных APK **1.2.9 / 10209**.
[F32-28](../audits/2026-09-20/CLONE-IDENTITY.md): clone identity fix установлен; OTA-only recovery добавлен, но удалённым копиям надёжно доставить APK пока не удалось. Viewer общей карточки получил SPS/PPS без IDR; кадр и декодирование не приняты. На 32 устройства допуск закрыт.
**Последний source-pinned debug candidate:** APK **1.2.11-dev / 10211**, исходники из PR head `6788c90704319b5cf17ea0d92c7803220ba1c9a0`. Включены bounded OTA body retry, strict VM-serial binding и Android backstop для раннего запроса IDR. Dev и enterprise suites: по 610 тестов, без failures/errors, по одному существующему skip теста baked-route. APK подписан сертификатом локального pilot, но **не установлен и не опубликован**. Перед OTA нужен backend v2 и canary с фактически подтверждённым ACK версии identity; 20 удалённых копий и первый browser-декодированный кадр остаются непроверенными. [AUD-145](../audits/2026-09-20/CLONE-BINDING-V2.md) · [AUD-142](../audits/2026-09-20/ANDROID-KEYFRAME-STARTUP.md) · [AUD-144](../audits/2026-09-20/OTA-TRANSPORT-RETRY.md).
[Canary 21 сентября](../audits/2026-09-20/CANARY-20260921.md): 15 task receipts,
два pipeline, pending stop/deadline и backend restart проверены; PID после OTA
сохранились, crash buffers прежние. Свежая APK и обычный OTA-каталог обновлены.
[AUD-138](../audits/2026-09-20/DECODER-RECOVERY.md) установлен поверх canary:
ограничение очереди и recovery decoder, 264 frontend tests, два реальных потока
и возврат после backend restart без F5 проверены.
32-device/8h acceptance открыта; sleep пока задерживает отмену до конца действия.

**Redis AUD-139 (`93551e0`):** ceiling 1536 MiB при прежних maxmemory 512 MiB
применён без restart. Redis и APK PID/crash buffers прежние, оба устройства online.
[Изолированная OOM/persistence приёмка и ограничения](../audits/2026-09-20/REDIS-MEMORY.md).
Поздний CI probe на PR head `e635de8` воспроизвёл OOM при параллельных AOF/write
операциях в отдельном контейнере. Source Compose теперь задаёт 2048 MiB; новый
все три isolated CI probe прошли без OOM. Cgroup peaks: 2.00, 1.49 и 1.84 GiB;
худшее наблюдение остаётся потолком 2 GiB. **Этот pilot
остаётся на 1536 MiB** до отдельного rollout и 32-stream acceptance.
[AUD-143 evidence и статус](../audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md).

История 20 сентября: backend `85fb1ea`, frontend `03b161e`, APK 1.2.7 (`0f257fe`). [Приёмка нового APK](../audits/2026-09-05/ANDROID-RECONNECT-DEBT.md)
подтверждает native OTA, команды/DAG/видео после обрывов и освобождение захвата.
Повторная ночь завершилась FAILED через 3 ч 33 мин; 223 DAG сверены, новых APK crash
нет. Исправление доставки старта захвата развёрнуто: 12 viewer-сессий после простоя
получили SPS/PPS/IDR, projection освобождена, PID прежние.
[AUD-125 и границы приёмки](../audits/2026-09-05/STREAM-START-DELIVERY.md).
Следующее исправление AUD-126 сохраняет кадры в нескольких окнах одного
устройства: три/два/один viewer на обоих APK прошли шесть этапов с прежними PID и
crash buffers; capture освобождён после собственных окон.
[Приёмка и сравнение до/после](../audits/2026-09-05/STREAM-MULTI-VIEWER.md).
Историческая приёмка Task Engine: 190 задач, восемь страниц, поиск старой задачи и
настоящий активный pipeline. Оба устройства выполнили echo после обновления.
[Приёмка истории и ограничения](../audits/2026-09-05/TASK-HISTORY.md).
Дополнительно: 12 shell/logcat-запросов без ложных missing-task warnings и два
13-node DAG с неизменными PID. На той приёмке total достиг 192 без reload;
после ночи API при развёртывании `8a6b30e` вернул 418 completed, активных задач нет.
[Разделение RPC и заданий](../audits/2026-09-05/INTERACTIVE-RESULT-IDENTITY.md).
Ниже сохранена датированная история предыдущих приёмок.

[Главная](../../README.md) · [Приёмка](PILOT-ACCEPTANCE.md) ·
[Готовность](READINESS.md) · [Android](../android-agent.md)

## Какая установка запущена

Новый Compose project — **`sphere-pilot-20260911`**, из checkout
`C:\Users\dimas\Documents\ChatGPT\sphere-platform`.
Дата в имени — постоянный идентификатор установки, его не меняют при перезапуске.
Старый project `sphere-platform` из `C:\Users\dimas\Documents\sphere-platform`,
его tunnel, контейнеры и volumes не используются новым стендом.

| Компонент | Адрес на рабочей станции | Проверено |
| --- | --- | --- |
| Web + API + WebSocket gateway | <http://127.0.0.1:18080> | Вход, dashboard, список устройств, reload с refresh сессии |
| API readiness | <http://127.0.0.1:18080/api/v1/health/readyz> | HTTP 200 через Nginx, PostgreSQL и Redis готовы |
| n8n | <http://127.0.0.1:15678> | HTTP `/healthz` 200; выполнение workflows ещё не проверено |
| MinIO S3 / console | `127.0.0.1:19000` / <http://127.0.0.1:19001> | Container health; прикладной screenshot flow ещё не проверен |
| PostgreSQL / Redis | Только собственная Docker network | Миграции и bootstrap, отдельные persistent volumes |

В Docker Desktop девять активных сервисов объединены под новым именем: семь
базовых и два для временного внешнего доступа. Backend и frontend
работают из собранных образов, без source bind mounts и установки npm при старте.
Backend выполняет четыре Gunicorn workers. Все девять сервисов имеют healthcheck и
`restart: unless-stopped`; после запуска Docker они возобновляют работу, если
оператор не остановил их вручную. Docker Desktop должен быть запущен.

Backend нового стенда обновлён с исправлением AUD-97; private overlay
`.local-pilot/backend-acceptance.yml` выбран local launcher. Frontend и APK этой
проверкой не заменялись. После 30 s недоступности Redis реальные команды вернулись
без перезапуска backend/APK, с той же WS session: первая через 9.47 s, затем 12/12.
[Ревизии, воспроизведение и residual risk](../audits/2026-09-05/REDIS-SUBSCRIPTION-RECOVERY.md).
Следующее обновление backend, AUD-98, исправляет источник режима Sphere в журнале
устройства: получены 100 настоящих строк с прежней APK за 0.531 s.
[Доказательство и ограничения](../audits/2026-09-05/DEVICE-DIAGNOSTICS-SOURCE.md).

Сейчас подключены **два** LDPlayer: `auto-ph-000` / V2266A и `auto-ph-001` / HD1910,
с различными device IDs. На момент AUD-99 APK `0f1410e` подтверждена хешем на обоих;
после ремонта отсутствующего NAT второй сети прошли параллельные команды и
повторный network recovery без перезапуска APK.
[Инцидент и приёмка двух устройств](../audits/2026-09-05/LDPLAYER-NAT-INCIDENT.md) ·
[Диагностика сети станции](LDPLAYER-NETWORK-RECOVERY.md).

Для этих двух экземпляров включена отдельная задача **`Sphere-LDPlayer-pilot-20260911`**:
раз в минуту, после входа текущего Windows-пользователя, без server credentials.
Конфигурация и status: `.local-pilot/station-network/`. Контрольный отказ NAT второго
экземпляра устранён автоматически: команда через 108.12 s после fault; первый
продолжал работать. [Приёмка, ресурсы и ограничения](../audits/2026-09-05/LDPLAYER-AUTOMATIC-RECOVERY.md).
На других станциях этот компонент нужно установить отдельно; он не входит в APK.

## Вход и управление

Логин **`admin@example.com`**. Уникальный пароль создан только для этой установки
и хранится в `.local-pilot/operator-credentials.json` в указанном checkout.
Секреты БД/Redis/n8n/MinIO — в `.local-pilot/pilot.env`; эти файлы игнорируются Git.
Admin и enrollment key принадлежат одной организации `local-pilot-20260911`.

На этой рабочей станции повторный запуск и статус выполняются из корня checkout:

```powershell
python .local-pilot/manage.py up -d --wait --wait-timeout 180
python .local-pilot/manage.py ps --all
python .local-pilot/manage.py logs --since 10m --tail 100 backend
python .local-pilot/verify_runtime.py
```

Сгенерированный local helper фиксирует `--project-name`, `--project-directory`,
`--env-file` и выбранные Compose overlays, удаляет конфликтующие Compose/config значения из
унаследованного environment. Он и installation manifest находятся в `.local-pilot/`
и относятся к этому компьютеру. Нельзя заменять эту команду обычным `docker compose
up` без выбранного project/env. Никакой `down -v` для первого тестирования не нужен.

Версионируемый профиль — [docker-compose.local-pilot.yml](../../docker-compose.local-pilot.yml).
Он применяется **после** base и full; требует Compose с `!reset`/`!override`.
На другом компьютере сначала нужны собственные env, agent config, schema migration,
admin и enrollment bootstrap; копирование одного overlay не подготавливает БД.

## Текущий веб

Frontend **`6dea6b4`** установлен в новом pilot. Device Stream сохраняет выбранные
карточки при offline, показывает переподключение и оставляет Stop доступным.
Исправлены backoff, восстановление после remote normal close, обнаружение
молчащего сокета и очистка retry timers. 208 frontend tests и TypeScript прошли.
Реальный браузер восстановил оба экрана после сетевого отказа без F5 или нового
нажатия Start. Online badge обновляется отдельно и не подтверждает свежесть кадров.
[Причина, runtime и ограничения](../audits/2026-09-05/WEB-STREAM-RECOVERY.md) ·
[Матрица сетевых проверок](../audits/2026-09-05/NETWORK-RECOVERY-NATIVE.md).

## APK именно для нового стенда

Готовый файл и `manifest.json` находятся в **`.local-pilot/apk/`**. Это подписанный
**dev debug APK**, а не production release. Пакет
`com.sphereplatform.agent.pilot.debug` позволяет установить его рядом с обычными
dev/enterprise сборками, сохраняя отдельные credentials и identity.

Актуальный source-pinned кандидат: **`SphereAgent-pilot-candidate-1.2.11-dev-6788c90.apk`**.
Путь: **`.local-pilot/apk/SphereAgent-pilot-candidate-1.2.11-dev-6788c90.apk`**.
SHA-256: `18935e44b43b2f731176677a2acf8d306821792eee0477901a4f2606a76e73b7`.
Размер 8,459,412 bytes; package `com.sphereplatform.agent.pilot.debug`, versionCode
10211 / `1.2.11-dev`, minSdk 26, targetSdk 35. `GIT_SHA` внутри APK совпадает с
полным source commit `6788c90704319b5cf17ea0d92c7803220ba1c9a0`; v2 подпись проверена,
SHA-256 сертификата совпадает с локальным pilot baseline. Полный APK manifest:
`.local-pilot/apk/SphereAgent-pilot-candidate-1.2.11-dev-6788c90.json`.

`LATEST-SphereAgent-pilot.apk` и публичный `manifest.json` по-прежнему указывают на
принятую ранее 1.2.9 / 10209; это **не** новый candidate. Alias и OTA-каталог
намеренно не переключались до backend-first canary. Candidate не ставился ни на
локальные, ни на удалённые устройства. Не ставить его массово: сначала развернуть
backend v2, затем на одном удалённом LDPlayer проверить отдельный стабильный device ID,
identity ACK, reconnect и цепочку реальный IDR → browser decode. Подробные результаты
предыдущей OTA-приёмки двух локальных APK: [canary report](../audits/2026-09-20/CANARY-20260921.md).

### История предыдущих APK и приёмок

Следующие версии, counters и ожидания относятся к датированным предыдущим
проверкам; `manifest.json` и alias всё ещё указывают на принятую 1.2.9, пока candidate
1.2.11 не пройдёт backend-first canary.

**1.2.7 / 10207 (`0f257fe`):**
**Оба Android обновились через собственный OTA**, без ADB install, Windows
launcher, ручных разрешений, очистки данных и новой регистрации. Первый перешёл
с 1.2.5, второй — с canary 1.2.6. Installed hashes и signed cache v14 проверены;
команды после OTA вернулись через 9.671 / 9.687 s соответственно.

AUD-119 снимает предел подтверждённых задач с сохранением migration/replay защиты;
AUD-124 сбрасывает старую retry debt после подтверждённого соединения. Полный
Android: 579 dev passed, enterprise 578 passed/один ожидаемый skip. Signed build:
164 выбранных теста на каждый flavor. Три native capture/stop цикла на каждом
устройстве прошли с тем же PID; repeated network faults вернули реальные команды,
DAG и кадры без новых crash records. [Evidence и границы](../audits/2026-09-05/ANDROID-RECONNECT-DEBT.md).

Проверки boot и прерванной/параллельной OTA на 1.2.4, исправление SIGSEGV и 10
циклов захвата на 1.2.5 остаются историческими; это не новые прогоны на 1.2.7.
[Capture incident](../audits/2026-09-05/ANDROID-CAPTURE-LIFECYCLE.md) ·
[OTA interruption](../audits/2026-09-05/ANDROID-OTA-RECOVERY.md).

На приёмке 1.2.7 в каталоге было **4 release android/dev: 10203, 10204, 10205 и актуальный 10207**;
оба промежуточных canary retired. Публикация в канал даёт версию периодическому
OTA worker; эти конкретные установки запущены серверной командой. Полный шестичасовой
интервал auto-check этой проверкой не измерялся.
Файл и каталог хранятся в `.local-pilot/updates/`, backend bind mount
`/var/lib/sphere/updates`. Пересоздание только нового backend сохранило каталог
и авторизованное скачивание актуального APK. На той приёмке backend был закреплён на **`12249b1`**,
public-gateway использует Host fix `985e4fc`.

В текущем backend исправлены ответы создания сценария и управления pipeline
([AUD-115](../audits/2026-09-05/SCRIPT-CREATE-RESPONSE.md),
[AUD-116](../audits/2026-09-05/PIPELINE-CONTROL-RESPONSE.md)). Native batch и
pipeline pause/resume/cancel приняты в описанных границах. 14 сентября в 05:06
Asia/Yekaterinburg запущен конечный восьмичасовой прогон `night-20260914-001`.
Его статус и evidence: `.local-pilot/soak/night-20260914-001/`. В 07:40 helper
завершился с `PermissionError` после 77 циклов; статус **failed**, без повтора.
Оба APK сохранили PID, результаты перепроверены. [Разбор и AUD-117](../audits/2026-09-05/ANDROID-SOAK-TERMINAL.md).
[Расширенный анализ](../audits/2026-09-05/NIGHT-RUN-ANALYSIS.md) подтверждает
ограничения Task Engine и 512 ACK receipts; их fixes ещё не установлены.
После отдельного визуального контроля добавлены два безопасных задания;
исходные ночные counters не менялись. Новый длинный прогон пока не запускался.
[Программа, остановка и чтение результатов](ANDROID-OVERNIGHT-SOAK.md).
[Передача кадров между workers](../audits/2026-09-05/STREAM-VIDEO-ROUTING.md) исправлена;
[AUD-113](../audits/2026-09-05/STREAM-IDLE-RECOVERY.md) устраняет restart здорового
захвата по Redis read timeout. Native 75 s на обоих: ровно один start на устройство,
24/24 echo, PID и online неизменны; после закрытия auto-stop. GET stream status пока использует worker-local
статистику; длительная стабильность/нагрузка и полное задание из UI ещё не приняты.
На обоих Android сохранён periodic update worker: 6 h при сети, retry от 30 s.
Полный шестичасовой период не выжидался; native установка инициирована сервером.
Будущие APK надо публиковать в этот каталог: один git commit или локальный LATEST
не являются выпуском OTA. Раздача проверенного файла требует действующего JWT.

### Параметры текущего подключения

Root projection принят на предыдущей APK `ce26a9e`; реализация сохранена и её
regression tests пройдены в обоих signed flavors текущей сборки.

Management URL и fallback в APK пусты. `SPHERE_CONFIG_URL` указывает на подписанный
документ в ветке `codex/pilot-bootstrap-20260911` отдельного config repository;
`SPHERE_CONFIG_MIRROR_URLS` — на `/bootstrap/agent.signed.json` pilot gateway.
Installation ID/public verification key заданы при сборке; enrollment credential
берётся из закрытого config этой установки. `SPHERE_DEV_APPLICATION_ID_SUFFIX=.pilot`.
[Точные параметры и обновление документа](../architecture/ANDROID-SIGNED-DISCOVERY.md).

Эта APK установлена на **оба доступных экземпляра**, `emulator-5554` и
`emulator-5556`. Хеш каждого установленного `base.apk` совпадает с manifest.
Другие станции этой локальной проверкой не обновлялись. При выборе файла
сверяйте versionCode, SHA-256, package ID и installation manifest.

Старый pilot APK с `10.0.2.2:18080` предназначался для host gateway эмулятора,
а не распределённых станций. Ошибка на этом адресе означает, что экземпляр всё ещё
использует такую сборку или старое provisioning. Обновление требует того же package
и signing identity; не очищайте app data ради смены маршрута.

**Текущий внешний адрес временный.** Он работает через исходящий Quick Tunnel,
но изменится при restart connector. Основной signed config находится на GitHub вне туннеля;
копия — на gateway. Автопубликация включена для этого стенда: задача
`Sphere-Publisher-pilot-20260911`, цикл 60 s и logon текущего Windows-пользователя.
[Контракт, состояние и остановка](DISCOVERY-PUBLISHER.md). Старый baked gateway
mirror APK после смены hostname недоступен; её основной GitHub source стабилен. [Remote profile, реальные проверки и ограничения](REMOTE-PILOT.md).
[Подписанный bootstrap и открытая инфраструктурная работа](../architecture/ANDROID-BOOTSTRAP-DISCOVERY.md).

## Доказательства и следующий тест

- На свежих volumes применена schema до `20260910_device_refresh_retry`, CLI
  создали admin и enrollment key. Browser login/dashboard/devices и refresh после
  reload прошли. Серверные данные не заменялись фиктивными online devices.
- Backend/frontend образы нового стенда: `a22fb54`. Четыре Gunicorn workers.
  После AUD-92 установленный APK выполнил 12/12 отдельных HTTPS `echo` запросов.
  Первый запрос непосредственно после backend restart ранее получил 503 до возврата
  WS подписчика; переходный отказ сохранён отдельно, не выдан за успешную команду.
- APK `c0c0783`: 498 JVM tests / 36 suites, без failures/errors/skips. На установленном
  APK gateway restart → новая WS session за 9.03 s, тот же PID/device ID, 0 новых
  регистраций. Provider connector не перезапускался; второй provider не проверен.
- Protocol probe отдельно проверил HTTPS enrollment, WSS auth/heartbeat/reconnect
  и удалил своё синтетическое устройство. [Повторяемый сценарий](REMOTE-PILOT.md).
- Объединённый локальный Python-прогон: **1526 passed / 368.66 s**, `tests/load`
  исключён как отдельный opt-in профиль. Deployment subset: **101 passed**.
  Coverage в этом локальном прогоне не измерялась; точный CI результат отмечается в PR.
- Текущая signed APK `9618a57`: 515 JVM tests / 37 suites, по 29 signed
  dev/enterprise tests (discovery и реальный logger). 17 прежних replica tests
  заменены 10 production-class проверками; native before/after диагностики принят.
- Историческая signed APK `0f1410e`: 522 JVM tests / 37 suites; в signed dev/enterprise
  дополнительно по 19 cases. На том же коде `f61cd5a` смена адреса при остановленном connector:
  271.61 s до echo; обратный переход успешен, PID/identity сохранены, 0 регистраций.
  [Полный native сценарий](../audits/2026-09-05/SIGNED-DISCOVERY-NATIVE.md).
- Итоговая APK: аварийный kill своего процесса → Android восстановил WS и echo
  за **7.2 s**, новый PID, прежние identity/cache v7, 0 регистраций.
- Все 9 активных сервисов healthy. Старые Sphere ID/image/state/mounts сохранены;
  у `sphere-tunnel` изменился StartedAt (16:42:38 UTC), причина не установлена.
  Команды управления им в тест не входили. 27 baseline containers полностью совпали,
  `/reverent_colden` отсутствует. Исходная inventory сохранена без подмены.

**Автоматическая публикация:** реальный restart коннектора → новый signed v8
за 39.97 s → APK echo за 250.83 s; без ручного config update и регистрации.
Текущий внешний адрес: `https://reach-further-loads-ran.trycloudflare.com`.
Last-known route/expiry/version publisher видны в
`.local-pilot/remote/publisher/state/status.json`.

**Дальше:** постоянные независимые ingress/config hosts, приёмка host reboot и renewal; второй
эмулятор с проверенной сборкой; web → DAG → durable result; VPN и failure drills.

**Пока не подтверждено:** полноценное задание из UI, стриминг, физические телефоны,
VPN, external PC-agent, длительная нагрузка и массовое восстановление. Native echo
не заменяет эти сценарии. WG/AWG router для нового стенда не настроен; нулевой
VPN dashboard не доказывает доступность router. Prometheus/Grafana/Loki stack этим
профилем не включён. n8n требует настройки workflows; health не равен интеграции.
