# Задания: снимки, исходный контекст и проверка установленного API

**Дата:** 2 октября 2026, Asia/Yekaterinburg (UTC+5).<br />
**Ревизия приложения:** `5fcf18a87f9a2ab198b1d145eae485218871bc01`.<br />
**Связанные находки:** [F16](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f16), [F17](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f17).<br />
**Статус:** исходные разрывы контрактов исправлены; полная приёмка Android → storage → browser остаётся открытой.

[Текущее состояние](../../operations/CURRENT-STATE.md) · [Журнал](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Доказательства](TASK-ARTIFACTS-AND-RERUN-EVIDENCE.json) · [PR19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Подтверждённые причины

| Участок | До исправления | Доказательство и предел |
| --- | --- | --- |
| Веб | `/api/files/{screenshot_key}` и замена React DOM через `innerHTML` | Такого handler в исходниках нет. Runtime 404 на историческом окружении не приписывается без наблюдения |
| API снимков | `ScreenshotStorage.__new__` без клиента; исключение скрывалось выдачей ключей вместо URL | Подтверждено исходниками и регрессиями, а не предположением о Cloudflare |
| Повтор | POST `/tasks` только с script/device/priority | Исходная версия и input_params не участвовали в создании |
| APK screenshot action | `takeScreenshot()` возвращает локальный Android path | В этой ветке DAG нет загрузки файла в MinIO и формирования screenshot_key |

Историческая фраза F17 «есть backend retry endpoint» оказалась неточной: на проверенном before source `9b1f0e1` task rerun endpoint отсутствует. Замороженный аудит не переписан; уточнение внесено здесь.

## Семантика повторного запуска

`POST /api/v1/tasks/{task_id}/rerun` принимает ID исходного задания. Клиент не передаёт копию его параметров и не выбирает вместо оператора текущую версию скрипта.

1. Проверяются permission `script:execute` и принадлежность task организации.
2. Исходная строка блокируется и перечитывается; допустимы только terminal статусы.
3. Отсутствующая pinned версия приводит к 409, а не выбору latest.
4. Проверяются доступность исходного скрипта, версии, устройства и явного account_id в той же организации.
5. В новой задаче сохраняются script_version_id, device_id, priority, timeout_seconds и глубокая копия input_params, включая webhook и custom значения.
6. Не переносятся batch_id, wave_index, старый result, времена исполнения и cancellation receipts. Это независимое задание, не возобновление старой волны оркестрации.
7. Существующий device lock и проверка активного задания не дают двум конкурентным запросам создать два активных повтора одной версии.
8. Результат HTTP201 означает сохранённое queued намерение. Dispatch выполняет существующий worker после commit; физическое выполнение этим ответом не подтверждается.

Кнопки в карточке и истории используют этот маршрут. В истории выданный ID открывается отдельным действием из уведомления; в карточке есть receipt и ссылка на новую задачу. Версия и семантика повтора указаны рядом с контекстом. Legacy repeat без recorded version недоступен.

У mutation явно задан `retry: false`. Потерянный ответ не повторяется автоматически даже при глобальных mutation retry defaults. Повторный явный запрос встречает 409, пока существует активная задача той же версии на устройстве. Это не полный протокол идемпотентности: если задача уже успела завершиться, следующий явный запрос может создать ещё одно исполнение.

Сохранение входов не означает восстановление внешнего мира: APK, состояние приложения и доступность аккаунта могли измениться с прошлого запуска. Произвольные input_params сохраняются, но новые способы их интерпретации в Android этим batch не добавлены.

## Контракт снимков

`GET /api/v1/tasks/{task_id}/screenshots` возвращает типизированный manifest:

```json
{
  "task_id": "<authorized-task-id>",
  "screenshots": [
    {
      "key": "tasks/<task-id>/<device-id>/capture/123.jpg",
      "url": "/tasks/<task-id>/screenshots/content?key=<encoded-key>",
      "unavailable_reason": null
    }
  ]
}
```

Повторяющиеся ключи node_logs/final_screenshot_key объединяются. Ключ чужой задачи или небезопасный путь получает явный unavailable_reason и не превращается в ссылку. Пустой manifest означает отсутствие ссылок в полученном result, а не отсутствие изображения на Android.

`GET /api/v1/tasks/{task_id}/screenshots/content?key=…`:

- Повторно проверяет permission `script:read`, org, namespace task/device и наличие ключа в сохранённом результате.
- Не принимает произвольный публичный URL, не перенаправляет браузер в Docker-сеть и не выдаёт credentials MinIO.
- Читает объект через штатный MinIO SDK, вне event loop.
- Ограничивает прочитанные данные 5 MiB; разрешает JPEG/PNG по сигнатуре. Полная декодируемость проверяется браузером отдельно.
- Возвращает `private, no-store` и `nosniff`; SVG/HTML не выдаются как снимки.
- Возвращает 404 для отсутствующего/удалённого объекта, 422 для неподходящего содержимого, 503 для недоступного или ненастроенного storage.
- Использует connect/read timeouts 1/3 секунды, без automatic SDK retries; response закрывается и connection освобождается в finally.

Веб использует общий авторизованный `api` client и Blob URL. Загрузка начинается только по кнопке, поэтому длинный журнал не скачивает все изображения. Есть loading, error, retry, hide, отказ от позднего ответа при смене task/key и revokeObjectURL при закрытии. Ошибка декодера обрабатывается React; кнопки не исчезают. Итоговый снимок показывается отдельно, если сервер действительно сообщил ключ.

Раньше route объявлял presigned URL, но фактически выдавал raw keys. Новая форма `screenshots` — массив структурированных references. Репозиторные потребители переведены на этот контракт; внешние потребители старой формы должны быть обновлены. APK этот read route не использует.

## Конфигурация и ресурсы

Опциональные server-side `SCREENSHOT_STORAGE_ENDPOINT`, `SCREENSHOT_STORAGE_ACCESS_KEY`, `SCREENSHOT_STORAGE_SECRET_KEY`, `SCREENSHOT_STORAGE_SECURE`, `SCREENSHOT_STORAGE_REGION` документированы в [.env.example](../../../.env.example) и передаются через [full compose](../../../docker-compose.full.yml).

Endpoint — `host:port`, без scheme/path. Для локального Docker это обычно `minio:9000` и secure=false; для TLS storage — secure=true. Нужен отдельный account с read policy на `sphere-screenshots`, а не общедоступный bucket. Этот batch не создаёт root credential для приложения и не публикует MinIO наружу.

На установленном pilot storage read configuration пока выключена. Manifest доступен, а чтение найденного объекта при такой конфигурации честно возвращает 503. Для интеграционного теста использовался отдельный временный MinIO контейнер; после теста удалён только этот контейнер по подтверждённому ID/label.

## Проверки

| Проверка | Результат |
| --- | --- |
| Текущие 19 backend regressions на изолированном before archive `9b1f0e1` | 14 failed / 5 controls passed / 0 errors |
| Полный frontend | 91 suites / 718 passed / 0 failed / 0 skipped |
| Дополнительный hook test с глобальным retry=3 | 2 passed, не больше одного POST при потерянном ответе |
| Task/script/storage unit suite | 92 passed; отдельный реальный MinIO test требует opt-in |
| PostgreSQL rerun + durable cancellation | 13 passed, реальные row locks и два конкурентных клиента |
| Реальный MinIO + авторизованные HTTP routes | 1 passed: объект → manifest → bytes → delete → 404 |
| Types / production build | passed; исходные production gates сохранены, SHA в compiled chunks |
| Ruff по изменённым Python файлам | passed |

Transport mocks/JSDOM не подменяют браузерную визуальную проверку. MinIO test использует тестовый бинарный объект, а не снимок удалённого Android. PostgreSQL тесты выполнялись только на отдельной loopback audit DB, не на pilot DB.

### Полный GitHub CI и исправление документации API

[Backend run36921814744](https://github.com/RootOne1337/sphere-platform/actions/runs/36921814744), application source `5fcf18a`: **2165 passed / 16 skipped**, coverage **78.00%**. Сам job завершился failure на следующем шаге: `export_api_docs --check` обнаружил устаревшие `docs/openapi.json` и `docs/api-endpoints.md`. Redis acceptance и зависимый Alembic job в этом run были skipped; их успех из прежнего head сюда не переносится.

Штатный exporter обновил оба файла до **171 HTTP operations / 134 paths**; local `--check` passed. Исторический frozen audit по-прежнему содержит 169 операций. [Текущий API-каталог](../../api-endpoints.md) и [OpenAPI](../../openapi.json) описывают зарегистрированное приложение, не гарантируют физическое исполнение Android. Экспорт не запускает lifespan и не обращается к устройствам.

[Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/36921814436) и [Android signed release smoke](https://github.com/RootOne1337/sphere-platform/actions/runs/36921814407) на том же source прошли. Новый verification head проверяется отдельно. Commit `3fe5eac` делает глобальные mutation retry defaults реальными в regression test; оба hook cases после этого passed, application code не изменился.

## Установленное окружение

- API source `5fcf18a`, **2 октября 01:27:36 UTC+5**: заменён только backend контейнер, image/build revision и readiness подтверждены. Старый image сохранён.
- Review UI source `5fcf18a`, **01:28:45 UTC+5**: `3015 → UI3030 / API18080`; Next772, relay13680. Предыдущий owned relay48892 заменён, Next7416/UI3029 сохранён для rollback.
- Server-only auth/Grafana/Prometheus конфигурация сохранена; APK, OTA и туннели не заменены. Public frontend остаётся предыдущей сборкой.
- **01:30:49 UTC+5**, запросы через relay3015: login passed; owned task manifest HTTP200; unknown-task rerun HTTP404 до создания задания; каталог 19 устройств, reported online14/offline5.
- Версии в этом срезе неоднородны: 10240 не установлен на весь парк. Срез не доказывает многчасовую стабильность и не измеряет FPS.
- Свежая визуальная приёмка Sphere: `OPEN_URL_POLICY_BLOCKED`; запрещённый просмотр не обходился другой средой.

## Оставшаяся часть Android artifacts

Follow-up **N01**: screenshot action автономного DAG сейчас даёт локальный path; нужна доставляемая загрузка артефакта, связанная с task/device/node/attempt, с receipt, ограниченной outbox, backoff, checksum, удалением локального файла только после принятия и storage retention.

До её реализации нельзя считать «любой screenshot из сценария доступен в вебе» подтверждённым. Интерфейс теперь отличает локальный path от серверного объекта. Это отдельный пробел; он не объясняет автоматически FPS/туннель или уже работающий capture видеопотока.

Следующая приёмка: настоящий APK screenshot на одном удалённом Android → зафиксированный ключ и checksum → HTTP image read → видимый снимок браузера → повторное открытие/удаление по retention. Конечный variable-only повтор pinned version подтверждён отдельным PH025 canary ниже; custom account/timeout и offline replay на Android ещё не приняты. Массовый прогон 20–30 устройств и закрытие PR19 ещё открыты.

## Официальные основания

- [MinIO Python SDK 7.2.20: get_object и освобождение response](https://github.com/minio/minio-py/blob/7.2.20/docs/API.md#get_objectbucket_name-object_name-offset0-length0-request_headersnone-ssecnone-version_idnone-extra_query_paramsnone).
- [FastAPI: прямой Response и явный media type](https://fastapi.tiangolo.com/advanced/custom-response/).

Новые библиотеки и UI assets не добавлялись. MinIO SDK уже является dependency проекта; его лицензия и авторство сохраняются. Этот batch не меняет AdminCN attribution и лицензии существующего дизайн-референса.

## Runtime и Android follow-up — 2 октября 04:51 UTC+5

Native review процессы исчезли после ранее записанной установки; причина не установлена. Review [3015](http://127.0.0.1:3015/) восстановлен в Docker: UI0f4530c / API5fcf18a, оба healthy, login/API/Prometheus/Grafana/events WS и restart passed. Все 14 прежних контейнеров сохранены. На remote PH025/10240 два variable-only задания completed/success; rerun исполнил pinned v1 после изменения latest v2. N01 upload, browser visual, массовые сценарии и video latency остаются открытыми. [Подробности и receipts](../2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md).
