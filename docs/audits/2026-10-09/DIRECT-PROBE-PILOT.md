# Прямой browser ↔ APK канал: первый native pilot

Дата: 9 октября 2026. Source пилота: `9ad3481c1173fdd508b43d0314ec6cf6ffbade1d`.
Scope: две ограниченные попытки открыть WebRTC DataChannel с PH011, только echo.
Видео, касания, клавиши и текст не передавались через экспериментальный канал.

[Машинное доказательство](DIRECT-PROBE-PILOT.json) ·
[Исходный контракт](DIRECT-PROBE-SOURCE.md) ·
[Изоляция viewer](DIRECT-PROBE-VIEWER-ISOLATION.md) ·
[Текущие работы](../../operations/WORK-STATUS.md).

## Результат и его границы

**Прямое соединение не установилось. RTT не измерен.** В обеих попытках браузер
завершил проверку по setup deadline 12 s: ноль echo samples, выбранная ICE-пара
не подтверждена. Это отрицательный результат native pilot, не успешная доставка
прямого media/control и не измерение задержки в 12 секунд.

При второй попытке read-only Redis observer подтвердил публикацию offer и answer
в авторизованном signaling. Offer: 652 bytes, один host/mDNS candidate;
answer: 723 bytes, два host candidate, без mDNS. В обоих SDP только
`m=application` и fingerprint. Между публикациями прошло **0,456 s**.
Observer не доказывает установку answer в браузере, DTLS или доступность
candidate pair. Raw SDP, IP, fingerprint, JWT и сетевые имена в публичный отчёт
не включены.

Native SDK действительно загрузил JNI, создал PeerConnection factory и начал
network monitoring. После каждой попытки наблюдалось unregister network observer.
Этого недостаточно для приёмки полного native cleanup, callback overflow,
stale callbacks и повторяемости сотен циклов.

Host-only ICE не гарантирует достижимость между Windows и Android-эмулятором.
Недоступность mDNS, виртуальные NAT/маршруты или firewall — **гипотезы**;
причина текущего отказа **UNKNOWN**, пакетной атрибуции нет. Нельзя объявлять
STUN или TURN готовым исправлением до отдельного сравнительного испытания.
Выбор доступной candidate pair является частью
[ICE](https://www.rfc-editor.org/info/rfc8445/), а сигналинг сам по себе не
устанавливает WebRTC connection: [нормативный WebRTC API](https://www.w3.org/TR/webrtc/).

## Установка и завершение эксперимента

Все четыре hosted CI для `9ad3481c` завершились success: Backend 37969383084,
Frontend 37969383138, Android 37969383314, Preview 37969383077.
Использован exact-source backend artifact; schema head до/после одинаков:
`20261006_script_catalog_metadata`. Миграции и seed не выполнялись.

API-only установка включила явный allowlist ровно PH011. Затем тот же проверенный
API установлен с `DIRECT_TRANSPORT_PROBE_ENABLED=false` и пустым allowlist `[]`.
Каждая операция сохраняла остальные **45 контейнеров**. OTA catalog SHA-256:
`5d5dcb5521277b51f366ea5370a2f7df5fd62696de0d5b7b86a56b443b03af10`.
Маршруты публичного веба, business WebSocket и bootstrap не менялись.

Canary APK собран из isolated tracked source, offline Gradle/max-workers 2,
стабильным pilot certificate и тем же package/version. Dev и enterprise JVM
прогоны: по 984 tests, 0 failures, 0 errors, 3 skipped. Native dependency
`io.getstream:stream-video-webrtc-android:146.7.0` pinned; полное происхождение
upstream source, reproducible build, SBOM и advisory acceptance остаются OPEN.

Изменялся только PH011, `emulator-5554`, package `com.sphereplatform.agent.pilot.debug`.
Прежний APK сохранён перед установкой и **восстановлен** в 18:19:47 UTC.
On-device SHA-256 после восстановления совпал с исходным `d8023bce`:
`6b177bcbac3bb319597630f34f88956bc79a6e0e3261508c2fe09708b393b013`.
Версия 1.2.49-dev / 10249; app data не очищались, OTA не публиковалась.

Последний recorded runtime: UI `d70f55c6`, API `9ad3481c`, probe endpoint
отвечает close 4003 / `direct_probe_disabled` **до отправки JWT**.
GET PH011 вернул 200/online. PostgreSQL и Redis readiness прошли.
Это установка API и конечная проверка возврата обычного пути; экспериментальный
native APK и диагностический UI сейчас не установлены на рабочем 3015.

## Ресурсы и обычный стрим

Четыре ограниченных native process samples одного PID:

| Срез UTC | VmRSS, KiB | Threads |
| --- | ---: | ---: |
| 18:12:14, до первой попытки | 123820 | 41 |
| 18:13:25, во время первой | 129912 | 42 |
| 18:13:51, после первой | 131184 | 39 |
| 18:16:47, после второй | 133344 | 37 |

Изменение RSS +9524 KiB (~9,3 MiB) включает загрузку JNI и две попытки.
Оно не доказывает отсутствие утечки и не устанавливает неограниченный рост:
нужны повторяемые циклы и учёт allocator/native ownership. Это не измерение
расхода всего ПК. Причина заполнения C: остаётся UNKNOWN; существующий
limited observer не расширялся этим пилотом.

После восстановления APK в установленном UI получены 13 decoded/drawn frames,
25 пакетов / 355901 bytes, decode/render/invalid errors 0. Это finite first-frame
return, **не** steady FPS или SLA. Повторился `idle_receipt_timeout`:
последний ACK RTT 256 ms, oldest heartbeat/deadline 512/512 ms, WS OPEN/0 B,
без удержанного пальца и terminal ACK. Причина и надёжность управления OPEN.

## Исправления, найденные пилотом

При explicit browser Stop socket мог закрыться до server final close; возникал
ASGI `WebSocketDisconnect`. Source correction ограничивает best-effort close
одной секундой и обрабатывает уже закрытый/отключённый/медленный сокет.
Lease retirement и общая изоляция worker сохраняются; replay/deadlines/auth
не ослаблены. 81 backend direct/continuous/bridge/keyframe regression passed.

Reviewed installer допускает только две явно выбранные probe env-переменные,
один canonical UUID либо disable с пустым allowlist. Полный Compose baseline,
installed environment, соседние контейнеры, schema и OTA проверяются;
environment drift вызывает rollback только принадлежащего операции API.
63 reviewed delivery/archive/admission tests прошли; Ruff/mypy passed.

Source UI показывает отдельно сбор адресов, signaling, установленный answer,
открытый канал и echo samples. Нет ответа — RTT «Не измерен», путь
«Не подтверждён»; raw reason вынесен в details. Late answer completion не
возвращает остановленный probe в active phase. Восемь focused frontend tests
и TypeScript passed. Временный 3016 визуально проверен на отключённом endpoint,
без native input; полный mobile UX этим срезом не принят. Временный сервер и
созданная проверочная вкладка закрыты. Эти новые source corrections ещё не
установлены; новый exact-source hosted CI — отдельный последующий gate.

## Следующий gate

1. Снять ограниченные browser/native ICE состояния и candidate-pair counters
   при отказе; сохранить отсутствие выбранного пути как UNKNOWN.
2. Разделить host reachability, mDNS и виртуальный NAT в контролируемом сравнении.
   Затем испытать явно настроенный STUN и credential-bound TURN fallback.
3. Проверить selected pair + echo RTT, повторные открытия, TTL/Stop/reconnect,
   auth revocation и native resource plateau. Не повторять Android input.
4. Только после этого подключать media/control с единственным владельцем,
   отдельным rollback и LAN/WAN/relay/version matrix. Direct echo не закрывает
   исходный idle ACK failure, recorder trajectory или product/fleet acceptance.

Product: **9 принято / 41 открыто**. Legacy: **7 незакрытых**. Закрытия пунктов
и новый SLA этой попыткой не заявлены. Частные файлы измерений находятся в
`.local-pilot/direct-probe-20261009/`; raw native logs могут содержать сетевые
данные и не включены в Git/PR. Публичный JSON хранит только bounded summary.
