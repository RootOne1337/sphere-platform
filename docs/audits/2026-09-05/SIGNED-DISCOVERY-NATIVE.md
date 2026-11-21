# Подписанная конфигурация: проверка на установленном APK

**12 сентября 2026 · один Android 9 эмулятор · временные публичные HTTPS маршруты.**

[Контракт](../../architecture/ANDROID-SIGNED-DISCOVERY.md) · [Пилот](../../operations/LOCAL-PILOT.md) ·
[JSON evidence](evidence/signed-discovery-native-20260912.json) · [HTTP cache fix](DISCOVERY-HTTP-CACHE.md)

## Проверенный результат

APK **`0f1410e`** получает management адрес из подписанного
JSON. `DEFAULT_SERVER_URL` и fallback пусты. В APK заданы GitHub Raw source,
gateway mirror, installation ID, открытый ключ проверки и отдельный enrollment
credential. JSON не содержит credentials. SHA-256 реально установленного `base.apk`
совпадает с артефактом: `3fea6b1be345bec99a71e1926a386dd070c361887d875d5b46a7c18d83d0d36b`.

Обновление выполнено через `adb install -r` того же package/signing identity.
App data не очищались. Device ID `85f2f935-7739-400e-9389-0d71227e8f0a` сохранён;
APK принял подписанный cache и выполнил настоящий shell `echo` через backend.

Код Android в итоговой сборке совпадает с `f61cd5a`; минутный query experiment
`9af3ee2` удалён после отсутствия native улучшения. На итоговой APK отдельно
проверены install без wipe, сохранённый подписанный v7 cache и настоящий echo.
Полные migration/return drills ниже относятся к указанным в таблице сборкам.

## Сценарий отказа и смены адреса

1. На сети только нового pilot создан временный второй outbound connector к его
   gateway. Нет host port forwarding, изменений VPN/firewall или старых контейнеров.
2. Основной connector нового pilot приостановлен через Docker pause. APK ещё хранит
   предыдущую конфигурацию; gateway mirror также недоступен через этот connector.
3. В отдельной ветке config repository опубликован новый подписанный version с
   другим management URL. APK получает его через GitHub, сохраняет проверенный
   envelope и сам устанавливает новую аутентифицированную WS session.
4. Через новый URL выполнен shell `echo`. PID и device ID не изменились, новых
   registration events — 0. Команд UI/ADB для reconnect или restart APK не было.
5. Основной connector возобновлён; выпущен следующий, больший version с исходным
   адресом и без fallback. После приёма APK этого документа временный connector
   остановлен. APK сам вернулся на исходный адрес, выполнил echo, сохранил PID и
   identity. Тестовый connector удалён. Итоговый signed version — **7**.

| APK | Смена адреса при отказе → подтверждённый echo | Возврат | Новые регистрации |
| --- | --- | --- | --- |
| `b8e8fe2`, до AUD-94 | 145.53 s | Успех | 0 |
| `f61cd5a`, только HTTP no-cache | 271.61 s | Успех | 0 |
| `9af3ee2`, удалённый query experiment | 284.23 s | Успех | 0 |

Это три отдельных наблюдения, а не статистическое сравнение latency. Время включает
обнаружение обрыва, публикацию GitHub commit, CDN propagation, polling, reconnect
и проверочную команду. Минутный query не дал измеренного улучшения и удалён. HTTP revalidation подтверждён
своим regression; эти наблюдения не доказывают мгновенное обновление GitHub CDN. В третьем прогоне
были диагностические GET с host и Android, что дополнительно исключает сравнение
как контролируемого latency benchmark. [AUD-95 остаётся OPEN](DISCOVERY-CDN-FRESHNESS.md).

## Как повторить

Используйте только свою изолированную установку и заранее доступный альтернативный
HTTPS ingress к тому же backend. Подготовьте новый payload и проверьте его
[offline signer](../../../scripts/discovery_manifest.py). Опубликуйте документ с
большей version через независимый source после отключения исходного канала.
Зафиксируйте время, APK revision/hash/PID/device ID, принятый version, новую
каноническую Redis WS session и результат команды. Один DB `online` недостаточен.

На debug APK проверенный public envelope доступен через `run-as <package> cat
files/signed-discovery.json`; токены из preferences не печатайте. Fault injection
оборачивайте в обязательное восстановление исходного connector. Возврат маршрута
публикуется с большей version; снижение version не поддерживается. Временный путь
удаляется только после приёма итогового документа и возврата устройства.

## Аварийное завершение итоговой APK

На APK `0f1410e` выполнен `kill -9` только её проверенного PID через
`run-as` собственного debug package. Android сам запустил новый процесс;
появилась новая аутентифицированная WS session и прошёл настоящий echo через
**7.2 s** от команды fault injection. Device ID и весь проверенный
signed cache v7 сохранились, новых регистраций — 0. Ручного запуска APK или
reconnect не было. Это не тест force-stop, reboot Android/host или всех OEM.

## Проверки и ограничения

- Default devDebug: **522 tests / 37 suites**, без failures/errors/skips.
- Signed devDebug и enterpriseDebug: по **19 discovery tests**, обе APK собраны.
  На Android установлена только dev pilot APK; enterprise OS acceptance не заявляется.
- Offline Python signer: **21 passed**. Deployment regressions: **101 passed**.
- Новый pilot: 9 healthy сервисов. У старой установки ID/images/states/mounts прежние.
  Старый `sphere-tunnel` имеет другое StartedAt (16:42:38 UTC) и RestartCount 80;
  причина перезапуска не установлена, команды управления им в тест не входили.
  27 исходных контейнеров полностью совпали; `/reverent_colden` отсутствует.

Два тестовых ingress используют одного провайдера; это проверка миграции, не
независимый резерв. После cleanup работает один временный ingress. Постоянный
второй config host, автоматический publisher/renewal, массовый reconnect,
physical devices, streaming, VPN и полное UI → DAG → result ещё не приняты.
Второй экземпляр со скриншота недоступен через текущий ADB и этим тестом не обновлён.
