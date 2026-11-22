# Android: файловый менеджер в браузере

Статус: **проектирование, не реализовано и не установлено**. Требование пользователя
от 15 октября 2026: окно в карточке устройства, которое показывает папки Android
и позволяет загружать/скачивать файлы с прогрессом, скоростью и возобновлением.
Текущий [визуальный аудит](../audits/2026-10-15/UI-UX-VISUAL-AUDIT.md) описывает общую
систему размеров и оформления. Рабочий APK 76/стрим этим документом не меняются.

## Фактическая база и новые составляющие

В APK есть OTA downloader/installer, bounded log upload, оригинальный screenshot,
shell и task execution. Веб скачивает последний APK и отдельные PNG artifacts.
Общих FS_LIST/FS_STAT и upload/download произвольного Android-файла с resume нет.
Эти существующие операции не считать готовым удалённым проводником.

Нужны три части: browser explorer, typed Android filesystem provider и ограниченный
transfer broker. PC Agent или дополнительный Windows-клиент для этого сценария
не требуется: пользователю достаточно браузера, эмулятора и APK.

## UX

В карточке устройства — компактное действие «Файлы» с Folder icon, рядом со стримом
и диагностикой. У окна явно указаны выбранное устройство и фактическая доступность;
переход на другое устройство не переносит туда очередь операций.

Desktop: окно до 1180×780 px, с поддержкой доступного resize. Header: название
устройства, путь, обновление, вид списка и закрытие. Слева — тома/избранные папки;
в центре — текущая директория; снизу — сворачиваемая очередь передач. У header,
списка и очереди отдельные размеры/scroll. Стекло допустимо на chrome, а строки
и поля остаются читаемыми рабочими поверхностями.

Телефон: полноэкранное окно, safe-area и явный возврат на уровень выше. Breadcrumb
сворачивается без потери текущей папки; tree открывается отдельным drawer.
Строка показывает Folder/File icon, имя, размер и дату; дополнительные действия —
через меню с touch area от 44 px. Очередь доступна одним действием и не закрывает
первичную навигацию. Проверить portrait, landscape и экранную клавиатуру.

| Действие | Поведение |
| --- | --- |
| Открыть папку | Результат привязан к device/volume/request; поздний ответ прежней папки не заменяет текущую |
| Скачать | Выбор назначения стандартным браузерным способом; доступно фактическое состояние передачи |
| Загрузить | File picker или drag/drop; передача начинается после ясного выбора папки назначения |
| Существующее имя | Явно выбрать заменить/сохранить копию/пропустить; не перезаписывать молча |
| Прогресс | Доставленные и подтверждённые байты, total, сглаженная скорость, ETA; не путать принятие сервером с сохранением на Android |
| Отмена | Подтверждённая остановка и очистка временного файла; неизвестный результат показан отдельно |
| Обрыв | Resume по server/Android offset и идентичности файла; не повторять rename/delete как новую операцию |
| Закрыть окно | Минимизирует очередь либо явно предлагает остановить; не сообщает ложный успех |
| Устройство offline | Последний список отмечен устаревшим; изменяющие действия недоступны, очередь честно показывает ожидание |

MVP: список/поиск в текущей папке, stat, download/upload, целостность, cancel/resume,
конфликт имени, ограниченная очередь. После этого — mkdir/rename/delete/multi-select,
предпросмотр и архивы. Recursive ZIP/распаковку не добавлять автоматически:
они требуют отдельных лимитов CPU, диска, глубины дерева и обработки прерывания.

## Android storage provider

Начальный каталог — доступные volumes и public shared storage: Download/Documents
и папки, явно разрешённые провайдером. Никакого обещания «все пути на любом Android».
Доступ различается между Android 9, современным scoped storage и rooted pilot.

Для user-selected дерева применим Storage Access Framework с сохранённым URI grant;
для media — соответствующий provider. Официальные ограничения и directory grant:
[Android documents/files](https://developer.android.com/training/data-storage/shared/documents-files).
Rooted managed provider — отдельная capability, а не молчаливый fallback любого
неудачного чтения. App-private `/data/data` не входит в обычный доступ.

Provider принимает типизированный volume/entry handle и операции. Имена, URI,
unicode и binary data не превращаются в shell-команду. Для rooted path provider
проверять фактическое разрешение пути, symlink и разрешённый root; нельзя обходить
ограничение через `..`, другой volume или гонку подмены пути.

Чтение метаданных выполняется в отдельном worker/dispatcher, без
`DeviceInputOwnership.claimDiscrete()` и native touch actor. Исходный конфликт
системного профиля/getprop не должен воспроизводиться в файловом списке.
Запись не проходит через shell/DAG/keyboard channel.

## Контракт и права

Ниже **предложение**, не существующие endpoints/API команды:

| Область | Контракт |
| --- | --- |
| Допуск | `files:read`, `files:write`, отдельно `files:delete`; org/device/volume scope и negotiated APK capability |
| Список | Оpaque entry ID, display name, kind, size, mtime, readable/writable, version; пагинация/cursor и ограниченный page size |
| Операция | operation ID, target identity, expected version, state, fixed error category, trace ID |
| Передача | transfer ID, direction, bound device/volume/path, declared total, offset, expiry, integrity state |
| Финализация | Только после подтверждённой записи и проверки размера/хеша; атомарное переименование временного файла, если поддержано provider |
| Конфликт | Conditional mutation по версии назначения; 409/typed conflict при изменении другим клиентом |
| Ошибка | unavailable / permission / no space / source changed / destination conflict / interrupted / integrity failed / cleanup unknown |

Не принимать путь к Android-файлу как URL для произвольного backend FileResponse.
Download/upload tickets короткоживущие и привязаны к actor/tenant/device/операции.
Повторный commit одного transfer ID не создаёт вторую запись. Directory names и
пользовательские байты не попадают в общие логи или stream telemetry.

## Готовые инструменты и транспорт

Для browser queue/progress/picker подходит набор Uppy Core + Dashboard/Tus с React
интеграцией и русскими строками. Подключать нужные plugins, а не полный CDN bundle:
[Dashboard](https://uppy.io/docs/dashboard/), [Tus plugin](https://uppy.io/docs/tus/).
Для файлового списка уже есть TanStack Table/Virtual. Большое дерево можно отдельно
оценить на готовом accessible Tree, например
[React Aria Tree](https://react-spectrum.adobe.com/react-aria/Tree.html), после проверки
совместимости и размера bundle. Ни одна из этих UI-библиотек не добавляет Android
filesystem provider или авторизацию сама по себе.

### Сначала надёжный резервный путь

HTTPS resumable upload через готовый tus server (кандидат [tusd](https://github.com/tus/tusd)) и обычный
streaming/range download. Авторизация и tickets остаются за API. Android получает
доступ только к принадлежащей операции и пишет файл через свой storage provider.
`HEAD` сообщает offset, `PATCH` продолжает upload; использовать ограничения,
expiry/cleanup и integrity подходящего уровня:
[tus protocol](https://tus.io/protocols/resumable-upload).

Upload завершён на сервере — отдельная стадия. Нельзя показывать «готово на Android»,
пока APK не подтвердил финализацию. Для скачивания также различать чтение Android,
доставку и завершение браузером. Передача не должна хранить целый файл в Blob/RAM
приложения; ограничения мобильного браузера и выдача download требуют отдельных тестов.

### Затем прямой путь

Метаданные и права согласует сервер; подходящий прямой route передаёт сами байты
между browser и APK. Это новый negotiated file protocol, например отдельный
`sphere-files-v1` data channel. Не помещать binary blobs в `sphere-control-v2`,
системные команды или существующий видеопоток.

Нужны bounded chunks, backpressure/ACK window, проверка offset/total/hash,
изменения исходного файла и устойчивого сохранения на APK. Отдельный SCTP stream
не означает полной независимости ресурсов от видео: сеть, CPU и память общие.
После смены пути подтвердить offset перед resume; старые route callbacks не
могут дописать файл новой операции. Relay fallback остаётся явным состоянием
конкретной передачи, без смены исправного video/control peer.

## Лимиты и метрики

Стартовые значения **для согласования и нагрузочного теста**, не заявленные
производственные пределы: directory page до 200 entries; 1–2 передачи на устройство;
память очереди/chunks фиксирована, например до 4 MiB на передачу. Не сканировать
весь Android рекурсивно при открытии окна. Большие файлы передаются потоково.

На сервере и Android: явная квота временного staging, TTL незавершённых передач,
уборка orphan после рестарта, лимит по tenant/device и проверка free space.
После успеха/отмены transient staging удаляется только в подтверждённом scope.
Не создавать очередной бесконечный архив на диске с каждой передачей.

Метрики: состояние, route, offset/total, rate, queue/buffer bytes, время ожидания
worker и IO, resume count, fixed failure/cleanup/integrity category. Не сохранять
имена и содержимое пользовательских файлов в общий pipeline ошибок. Отдельно
сравнить frame drops, video buffer и p95 control ACK до/во время передачи.

## Приёмка и поставка

1. Typed provider: Android 9 и современный Android, разрешённые/недоступные volumes,
   unicode/длинные имена, пустые и большие директории; без второго input owner.
2. UI: desktop/phone/landscape/soft keyboard, keyboard navigation, очередь,
   сохранённая папка на Back и корректные разные устройства.
3. Transfer: 0 B, маленький и большой файл; фактическое byte/hash совпадение;
   offline, reconnect, restart APK/browser, cancel, конфликт имени, no space,
   изменённый source, expired ticket и cleanup unknown.
4. Два одновременно записывающих клиента; ограничения observer/write/delete.
   Ошибки не скрываются и не превращаются в молчаливую перезапись.
5. Работающий direct stream и control не перезапускаются от открытия окна,
   прогресса, theme/sidebar change или новой файловой операции. Замер под нагрузкой.
6. Сначала отдельный canary и совместимость APK/API/Web, затем подтверждённая
   установка. Файловый менеджер не считается готовым по одному UI-мокапу.

Текущая подготовка APK 77 относится к диагностике задержек и native startup;
она не включает описанный файловый канал. Ни новый APK, ни backend/file service
в рамках этого аудита не установлены.
