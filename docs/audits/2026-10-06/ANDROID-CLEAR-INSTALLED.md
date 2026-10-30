# APK 1.2.46: установленный агент, очистка поля и выявленный screenshot gap

**Дата:** 6 октября 2026, Asia/Yekaterinburg. APK source `6a9f570f2c0a4dc54a90b0be57a289dadc85d534`.
**Установка:** 13:44:51–13:44:57 UTC. **Задание:** 13:48:42–13:48:57 UTC.
**Область:** один локальный PH011 / SDK28. **Статус:** функциональный canary принят;
полная приёмка APK, всех редакторов, удалённой сети и парка не заявляется.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Историческая сборка и helper-only proof](ANDROID-FOCUSED-TEXT-CLEAR.md) ·
[Новые pinned evidence](ANDROID-CLEAR-INSTALLED-EVIDENCE.json) ·
[Script Studio](../../operations/SCRIPT-STUDIO.md).

## Адресная установка с сохранением данных

PH011 сопоставлена с `emulator-5554` по двум независимым read-only ответам самого
агента: serial property и Android ID. Одного совпадения имени/версии недостаточно.
Device ID: `414ce0e9-4b93-4f96-b9ca-ee675f53835e`.
Подпись прежнего pilot debug APK 1.2.44 / 10244 совпала с кандидатом
1.2.46 / 10246. Старый APK и данные остановленного пакета сохранены в private
backup; их байты и конфигурация не публикуются в репозиторий.

Выполнен ровно один `adb install -r`, без удаления приложения или очистки данных.
UID остался 10082. Четыре shared-preferences файла побайтно совпали сразу после
установки, до явного запуска. После запуска приложение прислало новый heartbeat
с прежним device ID и кодом версии 10246. Само приложение может менять служебные
состояния/логи после запуска; их вечная побайтная неизменность не заявляется.
Состав каталога 19 устройств и версии остальных 18 сохранены. API, UI, OTA-каталог
и туннели не менялись. Это локальная установка кандидата, не штатная OTA-доставка.

SHA256 APK: `87db8510a091de310481c39804899ac6255a243df8f8de630db65d428d3dafc4`.
Cert SHA256: `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`.

## Один сохранённый сценарий и одно задание

| Receipt | Значение |
|---|---|
| Script | `47856351-7854-44f8-b6bb-a63712968409` |
| Версия v1 | `064a0cd9-cbe0-4412-8d99-385c9d40d6a7` |
| DAG SHA256 | `eb8864d121f89e3717374d2dda13c11e26d7d076507e2eed94ce4d196784315e` |
| Task | `043e6a3e-e68e-4967-9cd1-104685145adf` |
| Отчёты APK | completed; 25 / 25 success; 0 errors |
| Автоповторы | 0; каждый node.retry = 0 |

Settings Search используется как безвредный fixture. Перед вводом проверено
пустое поле. Сценарий вводит тестовую строку, сдвигает курсор внутрь, выполняет
`input_clear` и проверяет полное опустошение через отдельный XPath assert.
Затем повторяет очистку пустого поля и проверку. Второй seed заменяется командой
`type_text` с `clear_first:true`, тоже с курсором внутри. Итоговый assert и
`get_element_text` вернули точно `replacement-native`; после снимка выполнен Home.

ACK очистки по-прежнему содержит `field_verified=false`: подтверждение клавиш
само по себе не доказывает изменение editor. В этом fixture изменение отдельно
проверяют последующие XPath asserts. Native PNG также показывает итоговый текст,
но timestamp кадра не скоррелирован с XPath в общем frame timeline.

В native Codex browser проверены terminal status, версия, число отчётов и
раскрытый текст поля. Desktop 1280×900 не расширяет документ, console warnings/
errors в captured срезе — 0. Сохранён также исходный узкий viewport; временный
override восстановлен. «Повторить выполнение» не нажималась. UI `1c26ffc7`,
API `eb7a7c26` остаются прежними; MISMATCH — разные revisions, не диагноз ошибки.

## Новый подтверждённый дефект: PNG остаётся только на Android

Шаг `final_screenshot` сообщил успех за 301 ms и путь
`/sdcard/sphere_screenshot_1791294540156.png`. Серверный screenshot manifest пуст;
у node report нет `screenshot_key`. UI честно сообщает отсутствие файла на сервере.
Путь не является доступным веб-изображением. Он вручную прочитан через ADB только
для доказательства: original PNG 960×540 / 17441 bytes, без перекодирования.
Android SHA256 и downloaded SHA256 совпали. После сохранения удалён только этот
точно принадлежащий canary файл; отсутствие подтверждено.

В `AdbActionExecutor.takeScreenshot` source 6a используется новая уникальная
`/sdcard`-запись, fire-and-forget root command и фиксированное ожидание 300 ms;
проверки файла, count/byte/age retention и task upload нет. Это позволяет
накопление PNG при повторных screenshot/Lua/command вызовах. Этот код не
устанавливает причину роста Windows C: или 220 GiB Docker VHD: нужны отдельные
writer measurements. Общая история `/sdcard` не удалялась.

Следующий исправляемый срез: ограниченное локальное хранение оригинальных PNG,
реальное подтверждение screencap, ошибки capture без ложного success и проверка
границ удаления. Task-scoped upload, object lifecycle, authenticated artifact
receipt, reconnect/unknown reconciliation и frame replay остаются отдельными
критериями EP-019/020/047. EP-016 action schemas/capability preflight также открыт.

Исторические manifests не переписаны: `installed:false` в build receipt относится
к моменту сборки. Новый manifest фиксирует последующую адресную установку.
Общий backlog остаётся **9 принято / 41 с открытыми критериями**.
