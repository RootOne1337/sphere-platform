# AUD-98: журнал APK в интерфейсе возвращал пустой результат

**Severity: Medium · диагностика эксплуатации · 12 сентября 2026.**

Режим Sphere в API диагностики теперь читает существующий постоянный журнал APK.
На установленной APK один и тот же запрос до fix вернул только **58 символов /
2 служебные строки**, после — **100 строк / 13073 символа за 0.531 s**, включая
сообщения компонентов Sphere. HTTP 200 был в обоих случаях и сам по себе не
доказывал получение полезной диагностики. APK для этого изменения не обновлялась.

## Причина и затронутые файлы

[DeviceInspector LogcatViewer](../../../frontend/src/features/devices/LogcatViewer.tsx)
отправляет `mode: sphere` в `POST /api/v1/devices/{id}/logcat` и отображает поле
`logcat`. [Backend](../../../backend/api/v1/devices/router.py) всегда отправлял
`UPLOAD_LOGCAT`. В APK [LogcatCollector](../../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/LogcatCollector.kt)
оставляет только фиксированные теги; они не соответствуют class tags многих
действующих Timber messages. В release сборках [SphereApp](../../../android/app/src/main/kotlin/com/sphereplatform/agent/SphereApp.kt)
вообще не устанавливает DebugTree, но всегда пишет через FileLoggingTree.

Команда `REQUEST_LOGS` уже реализована в
[CommandDispatcher](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt)
и возвращает постоянные логи приложения. Интерфейс устройства её не использовал.
Это дефект выбора источника, а не доказательство отсутствия логов в приложении.

## Минимальный fix и совместимость

- Только `mode=sphere` (включая default) использует `REQUEST_LOGS` с запросом
  последних **64 KiB**; backend ограничивает вывод последними `lines` строками.
- Ответ сохраняет поле `logcat`, чтобы существующий viewer мог его отобразить.
- `mode=full` и остальные существующие logcat modes продолжают `UPLOAD_LOGCAT`.
- Tenant/device permission и интерактивный Redis request/result path сохраняются.
  Явная ошибка команды возвращается как ошибка, а не пустой успешный журнал.

Формат строк Sphere — timestamps и сообщения из файлов APK, а не системный
Android threadtime. Доступ ко всему системному logcat по-прежнему зависит от
Android permissions; собственный постоянный журнал не требует `READ_LOGS`.

## Доказательство и regressions

[Новые тесты](../../../tests/production/test_device_diagnostics.py) и
[доставка через настоящий Redis](../../../tests/production/test_interactive_command_routing.py):
**3 failed / 14 passed до fix → 17 passed после**. Проверяются выбор команды,
фиксированный byte request, последние строки, default/explicit Sphere, сохранение
full mode и ошибки; соседние случаи покрывают чужое устройство и offline path.

```text
python -m pytest tests/production/test_device_diagnostics.py tests/production/test_interactive_command_routing.py -q --no-cov
```

Нужны [изолированные PostgreSQL/Redis fixtures](../../../tests/production/README.md).
Ruff затронутых файлов прошёл. Native повтор использует отдельный новый backend,
одну Android 9/API 28 APK `0f1410e` и тот же публичный ingress. Запрос:
`POST /api/v1/devices/{own-device-id}/logcat`, body `{"lines":100,"mode":"sphere"}`,
с операторским Bearer token. До/после нужно оценивать содержимое, а не только HTTP.

[Evidence с request IDs, размерами и digest упакованного кода](evidence/native-device-diagnostics-20260912.json).
Текст журналов и credentials не публикуются. `request_id` связывает API запрос
с backend logs, но ещё не создаёт сквозную timeline device → task → command.

## Остаточные риски

Проверен API → Redis → установленный APK → настоящий журнал. Полный browser click
с отображением результата этой проверкой не подтверждён. Файлы имеют ротацию и
асинхронную очередь; это ограниченная локальная история, без центрального поиска
и гарантированной доставки каждого сообщения. Текущий reader считает смещение
файла в bytes, но пропускает символы через Reader: чтение больших UTF-8 файлов
требует отдельного regression и исправления в APK. Здесь этот reader не изменялся.
Уже удалённые журналы не восстанавливаются; время устройства может отличаться от
времени сервера. При недоступном APK новое чтение недоступно, нужен server-side архив.
