# Управление стримом между backend workers

**13 сентября 2026 · AUD-108 · High operational · REST controls приняты на real Redis и двух Android через четыре workers.**

[Аудит](AUDIT-REPORT.md) · [Готовность](../../operations/READINESS.md) · [Android capabilities](ANDROID-UNATTENDED-CAPABILITIES.md)

## Дефект и причина

На backend с четырьмя workers REST `start`, `stop`, `keyframe` проверяли только
локальный `ConnectionManager`. Android socket принадлежит одному worker; запрос
в другой worker возвращал 404 «Device not connected», хотя устройство online.
Это мешает как начать захват, так и остановить расход ресурсов на Android.

Повтор на текущем pilot перед deployment: **8 ложных 404 / 24 keyframe requests**
через отдельные HTTPS connections к двум устройствам; shell до/после работает
на обоих. Проекция этим baseline не запускается. Исходная более ранняя проверка
давала 2/16; числа относятся к разным выборкам, не к SLA.

## Исправление

REST controls используют существующий `PubSubPublisher.send_command_live`:
команда приходит в worker-владелец socket. Проверки организации и `stream:control`
выполняются до публикации. Команды интерактивные: они не добавляются в offline
queue. Нет подписчика — 503 command channel unavailable; ошибка Redis/неинициализированный
transport — отдельный 503 transport, без ложного «устройство не найдено».

При потере ответа Redis публикация могла уже состояться; автоматического повтора
нет, HTTP сообщает неопределённый delivery outcome. Ответ 200 означает запрос
на действие, а не подтверждённую проекцию или доставку кадра браузеру.

Affected: `backend/api/v1/streaming/router.py` и
`tests/production/test_stream_control_routing.py`. OpenAPI route/schema не меняются.

## Regression

18 HTTP cases на отдельных PostgreSQL/Redis: worker API без socket и отдельный
owner manager с настоящим PubSubRouter. Наличие подписки проверяется через Redis
до публикации; затем тест ждёт фактический send_json владельца и сравнивает команду.
По каждому endpoint проверяются offline без очереди, отсутствующий publisher,
ошибка Redis, чужое устройство и недостаточная роль.

**До: 12 failures / 18 cases. После: 206 passed**, включая 18 новых, interactive
HTTP routing и весь `tests/test_ws`. [Evidence](evidence/stream-control-routing-summary.json).

```sh
python -m pytest tests/production/test_stream_control_routing.py tests/production/test_interactive_command_routing.py tests/test_ws -q
```

Для real-service tests нужны `SPHERE_RUN_INTEGRATION=1`, loopback PostgreSQL
с `audit` в имени БД и отдельный Redis: [test contract](../../../tests/production/README.md).

## Native deployment и приёмка

Backend image source **`1310016`** собран из `git archive` только tracked runtime
paths, без локальных credentials/build-каталогов. SHA файла маршрута в image
сверен с archive и git source с учётом Windows CRLF. Заменён только backend
нового `sphere-pilot-20260911`; каталог двух OTA releases сохранён побайтно,
авторизованная выдача APK 1.2.4 сохраняет SHA. Старые Sphere IDs/images/states/mounts
не менялись в ходе deployment.

Первый helper ошибочно сравнил порядок Mounts в Docker inspect и откатил только
новый backend. Read-only повтор показал изменение порядка без изменения mounts;
сравнение исправлено сортировкой по Destination. Проба на временно возвращённом
старом image не засчитана как проверка fix. После повторного deployment:

- **24/24 keyframe HTTP 200** на отдельных соединениях вместо **8/24 false 404**.
  Shell-команды обоим устройствам до/после проходят.
- На обоих Android через REST выполнены start → keyframe → stop, отдельный HTTPS
  connection на действие. `dumpsys media_projection` подтверждает настоящую активную
  проекцию, затем `null`. Ожидание active после HTTP start: **0.625 / 0.625 s**;
  ожидание inactive после stop: **0.594 / 1.156 s**. Это локальные интервалы
  наблюдения после ответа, не end-to-end latency SLA.
- Ручных разрешений и ADB mutations нет; прежние PID и команды APK сохранены.
  После trial ни на одном устройстве не осталась активная проекция.
- Девять сервисов healthy; OTA APK остаётся **`fdd26c5`, 1.2.4 / 10204**,
  повторной сборки/переустановки для server routing fix не требуется.

[Полные native evidence](evidence/stream-control-native-20260913.json).

Source CI **`1310016`**: все обязательные workflows/jobs success;
[архив](evidence/ci-1310016-summary.json). Последующий documentation head
проверяется отдельно в PR, без переноса статуса предыдущего commit.

## Residual risk и следующая приёмка

- Viewer WebSocket, video bridge/frame delivery, stream status и reconnect/stop
  lifecycle всё ещё используют process-local state. Этот REST fix не закрывает
  полный стрим и не делает process-local status достоверным для всех workers.
- Успешная Redis publication не является ACK Android. Socket может исчезнуть
  после публикации; pending interactive commands не переигрываются молча.
- Следующий шаг: отдельный cross-worker video/lifecycle fix, настоящие viewer
  frames, reconnect, stop и отсутствие фоновой проекции без зрителя. Native REST
  start/stop не заменяет приёмку потока в браузере.
