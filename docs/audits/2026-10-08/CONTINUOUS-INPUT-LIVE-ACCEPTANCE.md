# Непрерывное управление PH011: установленная приёмка

8 октября 2026, 05:26–05:40 Asia/Yekaterinburg. API и UI source `28104f8`;
подписанный pilot APK `1.2.49-dev /10249`, Android source `d8023bc`.
Android sources между этими commits не отличаются. Канонический статус:
[CURRENT-STATE](../../operations/CURRENT-STATE.md).

## Установка и границы

Полный exact-source CI прошёл: backend3319 passed/37 skipped/229 subtests,
frontend1825 passed/137 suites, Android979 passed/3 skipped в каждом из
Dev и Enterprise variants. Canary flag включён именно в проверенных APK;
default/release flag остаётся false. Предыдущий failed backend run `cae8057`
сохранён в истории и не использовался для установки.

Reviewed API/UI installers проверили authenticated CI, source revision,
archive/config/manifest digest, HTTP readiness и сохранение45 остальных
контейнеров при каждой установке. Миграции не запускались. OTA catalog
сохранён этими installers; затем явно опубликован один nonmandatory canary.
Normal OTA channel не продвигался.

APK установлен только на PH011 (`414ce0e9-4b93-4f96-b9ca-ee675f53835e`),
одна попытка без очистки данных. Terminal receipt и следующий heartbeat
подтвердили10249, recovery grant снят автоматически. APK SHA-256:
`6b177bcbac3bb319597630f34f88956bc79a6e0e3261508c2fe09708b393b013`.
PH025 остаётся10248; PH010 и остальной парк не обновлялись.

## Независимая проверка живого пути

Настоящий authenticated WebSocket3015 → API → установленный APK → отдельный
Android View. После native STARTUP0 отправлены DOWN и пять MOVE с переменой
направления. View независимо показал move1,2,3,4,5 при up0/cancel0:
движение поступило до отпускания. Затем up1/cancel0 и native RELEASE3.
За конечный прогон показаны23 видеокадра. Receipt roundtrip247.53–253.63ms
измеряет ответ injector, не появление изображения на мониторе.

Настоящий браузерный drag через CUA дал независимые счётчики:
до down3/move27/up3/cancel0, после down4/move32/up4/cancel0.
Дельта: один DOWN, пять MOVE, один UP, ноль CANCEL. Последний MOVE принят
через121ms после начала; terminal через123ms. Это конечный жест конкретного
pilot, не общее обещание input-to-picture latency или frame-exact синхронизации.
Пользователь отдельно подтвердил работу вручную.

После ручного отключения режима native release вернул доступность навигации;
«Домой» подтверждено430ms, launcher виден. Тестовый receiver package удалён,
его отсутствие проверено. Основной agent package и его данные сохранены.

## Сохранённые неудачные прогоны и следующая работа

Первый прямой probe не посылал opening heartbeat, native owner истёк до READY;
Android input не отправлялся. Второй harness слишком рано прочитал View после
injector receipt. Финальный harness поддерживает heartbeat и ограниченно ждёт
независимое View обновление до отправки UP. Исходные failure reports сохранены.
При первом ручном подключении браузера режим остановился; причина этого
наблюдения полностью не установлена. Позднее стабильное подключение и жест
подтверждены. Cold startup probe показал STARTUP через579ms от probe и337ms
после session offer. Следующий UX этап отделяет bounded startup deadline от
500ms READY receipt deadline и требует собственной установленной приёмки.

Private evidence находится в `.local-pilot/continuous-live-20261008`:
`native-view-live.json`, `startup-timing.json`, `browser-before.json`,
`browser-after.json`, `browser-gesture.png`, `ph011-install.json`.
Это bounded snapshots без долговременного хранения кадров/траекторий.

SF26-05 остаётся OPEN: correlated recording, native crops/XPath evidence,
remote/fleet soak и failure qualification не завершены. Ledger9accepted/41open
не менялся. Не заявлены20–30 физических FPS, zero latency, overnight soak
или recovery после замены Redis. Дисковый incident и Git object recurrence
остаются самостоятельными открытыми вопросами.
