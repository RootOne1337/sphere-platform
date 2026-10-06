# Ошибки файловой системы рабочего ПК

Дата проверки: **6 октября 2026, 07:15 UTC**. Это отдельный инцидент Windows C:,
не заключение о причине расхода памяти, роста Docker VHD или сбоях Android.

## Подтверждено

При чтении старого, исключённого из Git контекста сборки Windows вернула ошибку
1392 «файл или папка повреждены». Read-only запрос журнала System с фильтром
`ProviderName=Ntfs, Id=55` подтвердил два события:

| Время UTC | Record ID | Подтверждённое сообщение |
| --- | --- | --- |
| 4 октября, 16:36:14.357 | 219586 | Повреждение структуры C:, природа неизвестна; Windows указывает на необходимость автономной проверки |
| 5 октября, 23:25:59.393 | 220528 | Повреждён индекс `$I30:$INDEX_ALLOCATION` старой временной папки тестов |

Вторая папка относительно репозитория:
`.local-pilot/script-studio-20261006/layout/context/frontend/__tests__/devices`.
File reference: `0x140000004e0a6e`. Это не текущие исходники `frontend/__tests__/devices`.
[Сокращённый receipt](evidence/host-filesystem/events.json) исключает имя пользователя
и несвязанные события других providers. Точное исходное сообщение получено из
System, а не выведено из размера папки.

Два loose Git tree объекта ранее были восстановлены с проверкой исходных SHA-1;
подробности сохранены в [отчёте Studio](STUDIO-REDESIGN.md). Последующий
`git fsck --no-dangling` **6 октября, 07:15 UTC** завершился exit 0.
Это проверка доступных Git объектов, а не всего диска или аппаратного состояния SSD.

## Что сделано и что не установлено

- Старый повреждённый контекст не используется для новых сборок; исключён его
  повторный рекурсивный обход. Новые контексты извлекаются из проверенного Git commit.
- Не выполнялись `chkdsk /f`, `chkdsk /r`, удаление повреждённого дерева,
  перезагрузка, изменение VSS или остановка Docker ради проверки.
- `fsutil dirty query C:` ранее отказал с Windows error 5. Флаг dirty остаётся
  неизвестным; отказ нельзя трактовать как «том исправен».
- NTFS events не доказывают физическую неисправность накопителя и не устанавливают
  writer, заполняющий диск. [Storage audit](../2026-10-05/HOST-DISK-GROWTH.md) остаётся отдельным.
- Новые тесты и сборки ограничиваются ресурсными воротами. Успешная сборка не
  закрывает файловый инцидент и не заменяет системную проверку в отдельном окне.

## Повреждённый generated class в Android-сборке

Отдельное наблюдение **6 октября, 12:30:32 UTC**, source `6a9f570f` / APK 1.2.46.
Первый полный EnterpriseDebug test run получил 19 `ClassFormatError` в
`WebSocketAuthenticationTest`: Java прочитала magic 4294967295 (`ffffffff`).
Это не assertion failures нового input adapter. Проверка четырёх соответствующих
файлов, а не предположение об ошибке кода, показала:

| Результат | Bytes | Magic | SHA256 |
| --- | --- | --- | --- |
| Raw Kotlin output Dev и Enterprise, transformed Dev | 1753 каждый | `cafebabe` | `bbc2ba76e9fafc358ce811c78a5c694cf4f3a47df7a3d8e31dbdeb6d02196840` |
| Единственный transformed Enterprise output | 1753 | `ffffffff` | `3d212e4aa7b626516a5554ca3ae6805da897d54578258a99e5a95456cddc1670` |

Повреждённый файл относительно проекта:
`android/app/build/intermediates/classes/enterpriseDebugUnitTest/transformEnterpriseDebugUnitTestClassesWithAsm/dirs/com/sphereplatform/agent/ws/WebSocketAuthenticationTest$http$1$1.class`.
Исходники не менялись. Перед удалением проверены resolved absolute path внутри
этого generated root и точный bad SHA256; исходные байты и failed build log
сохранены privately. Удалён **только один 1753-byte восстанавливаемый файл**, без
рекурсивного удаления дерева. Gradle повторил transform из корректного raw output.
Новый файл имеет `cafebabe` и исходный good SHA256; полный Enterprise suite затем
дал **855 passed / 1 assumption-skipped / 0 failed**. Dev suite имеет тот же итог.

[Сокращённый before/after receipt](evidence/android-focused-text-clear/generated-class-corruption.json)
сохраняет наблюдение повреждения и пересоздания; raw binary/log не публикуются.
[APK delivery](ANDROID-FOCUSED-TEXT-CLEAR.md) отдельно проверяет ZIP/DEX и signer.
Один повреждённый generated output **не устанавливает** причину: NTFS, storage
driver, RAM, внешнее изменение файла и compiler/toolchain требуют независимых
проверок. Наличие ранее записанных Ntfs55 не доказывает причинную связь.
Пересоздание файла не закрывает host incident и не устанавливает writer,
заполняющий C:. Offline filesystem repair или перезагрузка не выполнялись.

## Дальнейшая проверка

Перед автономным ремонтом нужен проверенный backup важных пользовательских данных
и проекта, согласованное окно остановки рабочих контейнеров и эмуляторов и
системная проверка Windows. Настоящий документ не разрешает автоматическую
перезагрузку или исправление файловой системы. После ремонта необходимы повторные
System events, проверка Git и hashes выпускаемых артефактов; отсутствие нового
события в коротком интервале само по себе не является приёмкой.
