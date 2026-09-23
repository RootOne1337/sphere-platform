# AUD-148 · Повторная live-приёмка удалённых LDPlayer

**23 сентября 2026 · pilot `sphere-pilot-20260911` · результат: регистрация восстановлена, видеоприёмка не пройдена.**

[Предыдущий срез AUD-147](REMOTE-FLEET-LIVE-AUDIT.md) ·
[Fleet32 gates](../2026-09-20/FLEET32-PREFLIGHT.md) ·
[Текущий pilot](../../operations/LOCAL-PILOT.md) ·
[Cloudflare route risk](REMOTE-FLEET-LIVE-AUDIT.md#проверка-гипотезы-cloudflare-quick-tunnel--f32-20)

## Решение

**Не начинать массовый тест на 20–32 устройствах.** Блокировка новых устройств
offline подтверждена как несовпадение протокола регистрации backend/APK и устранена
backend-first rollout без повторной установки APK. Семь известных записей
`auto-ph-000`–`auto-ph-006` после регистрации с binding v2 появились online. Это
подтверждает семь device IDs, но не доказывает, что заявленные 20 удалённых клонов
и два локальных устройства все одновременно представлены и устойчивы.

**Удалённое видео по-прежнему не принято.** Remote PH006 проходит регистрацию,
получает команды запуска и keyframe, но сервер за время viewer-сессий получает только
SPS/PPS — ни одного IDR или P-frame. Локальный `auto-ph-000` через тот же публичный
Quick Tunnel передаёт IDR и P-кадры. Следовательно, viewer/backend умеют доставлять
декодируемое видео через этот маршрут; полный отказ маршрута или всеобщая блокировка
кадров размером больше 16 KiB не объясняют наблюдаемую разницу. Это не исключает
проблему конкретного WAN-соединения, Cloudflare edge/маршрута Rostelecom или
LDPlayer capture/encoder.

## Установленная причина offline-карточек

До backend rollout pilot работал на `3be0e29`, который не возвращал APK обязательное
подтверждение `instance_binding_version=2`. APK 1.2.11/10211 ожидает совпадающий ACK
до сохранения registration credentials. Backend создавал карточку в PostgreSQL,
однако клиент не переходил к устойчивой аутентификации основного command WebSocket.
Это объясняет состояние «карточка есть, устройство offline».

Backend нового pilot обновлён до исходников `2f8b6c2` (образ
`sphere-pilot-20260911-backend:2f8b6c2`). Без переустановки клиент повторил регистрацию,
получил binding v2 ACK, прошёл WS authentication; Redis presence и API показали
online для `auto-ph-000`–`auto-ph-006`. PostgreSQL до rollout был сохранён в закрытом
локальном backup и проверен `pg_restore --list`. Frontend, APK, tunnel, старый Compose
project и старый tunnel не менялись. Удалённые APK версии 1.2.11/10211 указаны
пользователем; их установленный SHA локально не считан.

## Воспроизводимое сравнение видеопути

Оба источника тестировались с текущим backend и публичным Quick Tunnel. Метрики
касаются binary frames, принятых серверным viewer WebSocket; они не означают
успешного декодирования на удалённом клиенте.

| Источник | Viewer-сессия | Полученные данные | Вывод |
| --- | --- | --- | --- |
| Удалённый PH006 | 42.06 s | 4 binary frames: 2 SPS + 2 PPS; 0 IDR, 0 P-frame | Живое изображение не могло декодироваться |
| Удалённый PH006 | 20 s | 2 binary frames: SPS + PPS; 0 IDR/P; первый config через 8.172 s | Кадры изображения отсутствовали; одновременно diagnostics запрос завершился 504 |
| Удалённый PH006 | 18.02 s | 2 binary frames: SPS + PPS; 0 IDR/P | Повтор того же отсутствия видеокадров |
| Локальный `auto-ph-000` | 12.78 s | 6 binary frames, 42,789 bytes суммарно, максимум 40,351 bytes; SPS=1, PPS=1, IDR=1, P=3; первый через 1.406 s | Этот публичный маршрут пропустил крупный IDR и обычные кадры |

В backend для PH006 зафиксированы `viewer_connected`, `start_stream` и отправка
`request_keyframe` на авторизованный Android WS. В приватном фильтрованном logcat
видны `SSLException: Read error ... Connection reset by peer` и OkHttp ping timeout,
после которых агент переподключается. Сервер не получил image NALs; имеющихся логов
недостаточно, чтобы определить, не сформировал ли MediaProjection/MediaCodec IDR
или он сформировался, но не прошёл через конкретное WS/WAN-соединение. Android
`StreamQualityMonitor` считает кадры локально, однако его статистика нигде не
публикуется и backend не может сопоставить `ImageReader → encoder → sendBinary`.
Это следующий конкретный пробел диагностики.

Cloudflare описывает возможное throttling соединений через некоторые российские
сети примерно на уровне 16 KiB; это делает WAN гипотезу правдоподобной, но локальная
передача 40,351-byte frame через тот же Quick Tunnel не подтверждает её для этого
конкретного remote-соединения. Quick Tunnel предназначен для разработки и теста,
не имеет SLA. Поэтому attribution на Cloudflare/Rostelecom без A/B-сравнения по
независимому ingress преждевременен. [Cloudflare: проблемы доступности по регионам](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/service-disruption/) ·
[Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) ·
[Cloudflare WebSockets](https://developers.cloudflare.com/network/websockets/).

## Исправления кода и проверка

- `239171f` ограничивает объём запрашиваемого device log по числу строк. Это
  предотвращает выдачу полного 64 KiB журнала для маленького запроса. Реальный запрос
  `lines=1` к PH006 прошёл примерно за 0.17 s и вернул 144-byte response. Во время
  stream отдельные запросы `lines=10` всё ещё завершались 504 за 15 s; причина
  зависания по доступным данным не доказана.
- `2f8b6c2` игнорирует backend `noop` keepalive на Android, чтобы он не проходил в
  parser команд и не создавал ложный `Cannot parse command` warning. Код уже в
  проверенном source, но **APK с этим изменением ещё не собран, не OTA-опубликован и
  на устройства не установлен**. Этот change не объявляется исправлением видео.
- Backend regression: `24 passed` для бюджета диагностики и binding/registration;
  Ruff и `git diff --check` прошли.
- Android `CommandDeliveryTest`: `10/10` для dev и `10/10` для enterprise flavor.
  При сборке остаётся предупреждение: AGP 8.3.2 официально проверен до compileSdk 34,
  проект использует compileSdk 35. Это не блокировало тесты, но требует отдельного
  обновления toolchain.

## Остаточный риск и следующий критерий

1. Нужны app-side counters или журнал с агрегатами по текущей capture session:
   `ImageReader` acquired/rendered, encoder outputs by NAL class, `sendBinary`
   accepted/rejected, bytes and monotonic timestamps. Не логировать сами кадры,
   credentials или непрерывные per-frame записи. Это позволит локализовать пропажу
   данных до encoder, в WS sender или после sender.
2. Одновременно собирать transport counters по одной viewer-сессии и проверять
   первый декодированный browser frame. Backend receipt IDR сам по себе не является
   browser decode acceptance.
3. Только после canary на PH006 — сравнить тот же APK/устройство через независимый
   ingress. Сейчас другой route и адреса для такого теста не настроены; наружу ничего
   не разворачивалось.
4. После подтверждённого remote IDR+decode проверить отдельную регистрацию каждого
   из 22 устройств и reconnect после разрыва сети; затем нагрузка на 32 устройства.

До выполнения этих gates Fleet32 остаётся **NO-GO**. APK source fix не равен OTA
release, локальный stream не подтверждает remote LDPlayer capture, а online presence
не подтверждает свежесть кадров.
