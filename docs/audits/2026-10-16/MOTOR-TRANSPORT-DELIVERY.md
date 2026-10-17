# Поставка headless-транспорта и APK77

16 октября 2026 · конечная проверка установленного пилота, без модели и gameplay.

Backend обновлён на 3015 и Tuna до 27f3a61f. Все четыре доступных эмулятора
завершили адресное OTA до 1.2.77-dev /10277. Обычный веб 19c4272b сохранён:
его работа с новым API/APK проверена через оба адреса. Машиночитаемая квитанция —
[MOTOR-TRANSPORT-DELIVERY.json](MOTOR-TRANSPORT-DELIVERY.json).

## Что установлено

| Компонент | Состояние |
| --- | --- |
| Backend | Source 27f3a61fa5f2f3d2c1d8d56ed1dce7dbffe024a2; PostgreSQL/Redis ready на обоих адресах |
| Веб | Source 19c4272b3fffa98fdf7a35bd56b09967ac036e24; прежний проверенный контейнер сохранён |
| APK | Подписанная pilot-сборка 1.2.77-dev /10277, общий signer прежний |
| PH010 /PH011 /PH025 | Completed OTA, текущая версия и точный SHA установленного пакета |
| PH030 | Completed OTA и текущая версия; чтение установленного SHA занято непрерывным вводом |
| Остальные 17 | Офлайн; не обновлены, новые grants им не выдавались |
| Модель /GPU inference | Веса не скачаны, модель не установлена и не запускалась |

SHA APK: 9144dc1a25c9ced752fdec392580b6322db7d189817aed9591aa7e34cc2f0f5e.
Размер: 57 836 037 байт. Артефакт опубликован в android-canary/dev, mandatory=false;
обычный Android-канал сохранён. Полная авторизованная загрузка совпала по размеру/SHA,
анонимный запрос получил 401. Обновление не очищало данные приложения и не использовало ADB install.

PH030 уже на APK76 не позволял shell-инспекцию при активном continuous actor.
Для него перед OTA проверены текущая версия и точная прежняя completed OTA-квитанция;
свежий хеш старого пакета отсутствовал. Обновление выполнил штатный APK updater
с проверкой пакета, версии и подписи. После OTA ограничение инспекции сохранилось:
это частичная package-проверка, а не подтверждённый installed SHA. Ввод и его fence не сбрасывались.

## Что изменилось в транспорте

Установлен отдельный capture-only lifecycle для клиента без браузера. Backend сохраняет
авторизацию и presence, но не создаёт этому viewer серверную video queue/subscription.
Готовность источника подтверждает native quality RPC, затем worker проверяет первый
direct кадр, capture identity и самостоятельный native READY канала управления.
Потеря capture-only аренды не включает relay незаметно.

Backend и APK77 отклоняют recvonly SDP с объявлениями несуществующего sender SSRC/MSID
до передачи в native WebRTC. Это устраняет обнаруженную несовместимую форму offer;
исправление всех возможных native abort не заявляется. В APK также включена подготовленная
диагностика задержки очереди/исполнения shared input. Нового игрового исполнителя в нём нет.

## Проверки на установленной системе

На PH011 обычный Chrome прошёл один и тот же сценарий через 3015 и Tuna:

- Два независимых контекста, включая настоящий браузерный touch input.
- 12 раундов одновременных mouse/touch нажатий на каждом адресе.
- По четыре native applied для «Домой», «Недавние», «Назад», «Меню» у каждого участника.
- 30-секундное окно после нажатий с direct video/control ready и одним основным peer на клиента.
- После закрытия первого участника второй подтвердил ещё одно «Домой» и сохранил поток.
- Серверные shell/key и touch-команды: 0; page errors: 0. Все созданные контексты закрыты.

Это проверка двух участников на данном canary, а не новая приёмка 20+ пользователей,
реального телефона, PH030 или всей сетевой матрицы. Полный текст/IME в этом этапе заново не проверялся.

Headless worker 0.2.0 на установленном API/APK77 получил:

| Прогон PH011 | Окно | Decoder outputs | RGB observations | Native idle ALIVE |
| --- | --- | --- | --- | --- |
| Один клиент | 15,016 с | 885 | 75, около 4,995 Гц | 49 |
| Два клиента: первый | Около 12 с | 695 | 61 | 39 |
| Два клиента: второй | Около 25 с | 1442 | 126 | 81 |

Во всех трёх прогонах source readiness, отдельный READY и закрытие своего участника
подтверждены; server→headless video с запуска — 0 байт. У одиночного клиента decoder
работал около 57,8 FPS при выборе RGB около 5 Гц. Закрытие короткого клиента не оборвало длинного.
Последний полученный кадр осмотрен: читаемый launcher 960×540. Эталонная цветовая приёмка не выполнена.

Наблюдения RGB ещё не являются решениями модели. Worker отправлял только idle admission/ALIVE/CLOSE,
без игровых нажатий. Его RTT около нескольких миллисекунд не измеряет capture→action→screen latency.
Private ICE pair подтверждает peer-транспорт, но не доказывает LAN или отсутствие VPN.
Нулевой APK→server трафик с самого запуска и независимость от signaling не приняты.

## Локальная сборка, CI и установка

Полный локальный backend-прогон для точного source 27f3a61f: 4157 passed,
11 skipped, 511 subtests; JUnit содержит 4168 записей. Выполнены action contract,
RLS, fresh migrations, тесты с отдельными PostgreSQL/Redis и проверка HTTP API документации.
Изолированные сервисы и checkout удалены. PostgreSQL local image отличается от cloud reference;
полная идентичность окружений не заявляется.

Android собран в чистом output без build cache: dev и enterprise debug lint/assemble/unit;
по 1212 тестов, 0 failures/errors, 3 skips в каждом варианте. Два skip связаны с Windows symlink,
один — с предположением о baked URL, который в signed-bootstrap сборке намеренно пуст.
Это не полный cloud matrix всех Android-вариантов.

Результаты привязаны к source-коммиту на GitHub: Sphere Local / Backend regressions
и Sphere Local / Android candidate build. Hosted Actions для этой поставки не запускались.
Это ещё не означает автоматический перенос всех workflow и всех проверок каждого будущего коммита.

Backend упакован [локальным способом](../../operations/LOCAL-BACKEND-DELIVERY.md):
canonical Git bytes, точный установленный parent image и прежние dependency layers,
без установки зависимостей/сети при build и без image.tar.gz. Сам образ прошёл изолированный
application runtime probe и две проверки метрик с четырьмя workers, recycle и restart master.
Затем заменён только backend; 45 остальных контейнеров, SQL schema и transport/mDNS настройки сохранены.
Прежний backend image оставлен для rollback. Текущая schema: 20261006_script_catalog_metadata;
live migrations и seed не выполнялись.

Первый snapshot локального CI остановился до тестов из-за повреждённого Git object.
Шесть объектов восстановлены из GitHub с проверкой их Git SHA; итоговый git fsck — 0.
Неуспешный запуск и успешный полный повтор сохранены отдельно, а не объединены в один зелёный прогон.

## Следующая работа

Дальше — общий игровой profile executor: удержания, несколько пальцев, нейтральное состояние,
TTL/cancel и native action receipts; затем worker identity, observation/action clock contract
и atomic DAG→episode delegation. Только после этого — supervised игра и измерение GPU capacity.

Для развёртывания модели остаются нужны SSH-адрес, ОС, GPU и VRAM отдельной станции.
5 Гц управления, доезд к метке в Black Russia и 50×5 Гц ещё требуется доказать испытанием.
Открытые дефекты восстановления/цвета и полный production SLA этой поставкой не закрываются.

[Общий план](../../design/MOTOR-AI-PLATFORM.md) ·
[Запуск headless worker](../../operations/MOTOR-WORKER.md) ·
[Предыдущий capture-only кандидат](MOTOR-CAPTURE-ONLY.md).
