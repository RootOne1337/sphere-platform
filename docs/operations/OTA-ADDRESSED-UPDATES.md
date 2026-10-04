# Адресное обновление Android: действия и проверка результата

**Последний live readback:3 октября2026,03:17:58 UTC.** UI `77fca37`,API
`facba9a`; 14 адресных установок1.2.41-dev/10241 подтверждены exact receipts и
новым heartbeat; 14 online10241,5 offline вне приёмки. 12 finite срезов сохранили
cohort/epochs, heartbeat <30 s. [Новый отчёт](../audits/2026-10-03/OTA-RELEASE-IDENTITY.md).
Normal/dev10209, debugcanary не продвинут в global; general manifest/bulk/stable
и next-upgrade native guard acceptance OPEN. [Publication/APK checks](OTA-PUBLICATION-AND-APK-CHECKS.md).
Предыдущая10240 волна сохранена в [отдельном отчёте](../audits/2026-10-03/OWNED-PILOT-OTA-ROLLOUT.md).

[Текущее состояние](CURRENT-STATE.md) · [Доказательства F33](../audits/2026-10-02/OTA-ADDRESSED-DELIVERY.md) ·
[HTTP contracts](../api-endpoints.md) · [Архитектура OTA](../architecture/ANDROID-OTA-RELIABILITY.md)

## Где открыть

[Проверочный веб: OTA Updates](http://127.0.0.1:3015/updates). Это установленная
production-сборка review, подключённая к настоящему pilot API. Public frontend
этим этапом не заменён. Обычные данные входа pilot используются через тот же origin.

Для managed Android APK откройте «Адресное OTA». У остальных ролей доступно
«Состояние OTA»; выдача, повтор доставки и отзыв требуют `super_admin`.
Запись релиза в каталоге сама по себе не устанавливает APK.

## Перед отправкой

1. Выберите platform/flavor и опубликованный APK. Адресный workflow доступен для
   `android`/`android-canary` с managed URL `/api/v1/updates/artifacts/{sha256}`.
2. Выберите одно устройство. Каталог читает серверные страницы по50, поддерживает
   поиск; выбранное устройство проверяется отдельным GET с тем же UUID.
3. Сверьте package, flavor и сертификат с установленным приложением. Каталог
   **пока не предоставляет проверенный manifest этих полей**. UI явно просит
   подтвердить совместимость; это действие оператора, а не автоматическая проверка.
   APK10241 дополнительно проверяет файл непосредственно перед обоими installer
   paths; старые клиенты могут не иметь guard. Отчёт10240→10241 не доказывает
   живую работу нового guard. [Точный контракт/коды](OTA-PUBLICATION-AND-APK-CHECKS.md).
4. Сверьте сообщённую версию, состояние связи и heartbeat. Версия не ниже целевой
   блокирует повторную установку/downgrade в этом workflow. Неизвестная версия
   требует проверки совместимости; её отсутствие не подменяется нулём.
5. Выберите срок10/30/60 минут и выдайте разрешение. Срок ограничен сервером60–3600 s.

## Что означает ответ

| Сигнал | Что действительно подтверждено |
| --- | --- |
| HTTP 201 | Подписанное разрешение сохранено для одного device/hash/version/deadline |
| `wake_published` | Redis сообщил наличие подписчика; установка ещё не подтверждена |
| `awaiting_connection` | Нет доступного live signal; сохранённое разрешение остаётся до срока |
| active | Сервер проверил подпись/срок разрешения; ждём терминальный результат Android |
| expired | Срок разрешения истёк; старое разрешение не действует |
| invalid | Метаданные разрешения не прошли проверку; запись в UI блокируется |
| completed receipt | Android сообщил завершение конкретной команды и установленную версию |
| «Установка и heartbeat подтверждены» | Совпали hash/version receipt, сообщённая версия устройства, online/busy и heartbeat после receipt не старше60 s |

Старая receipt другого APK не подтверждает выбранный релиз. После ошибки чтения
cached rows не становятся актуальным состоянием. Ошибка записи означает
неопределённый результат: сначала «Обновить состояние», затем решение о повторе.
Автоматического повторного POST нет. Grant authorization tag не возвращается в UI.

## Повтор доставки и отзыв

- «Повторить доставку» отправляет сигнал **того же command_id**. Он не создаёт
  новое разрешение и не продлевает срок. Устройство должно успеть подключиться
  и завершить путь обновления в пределах действующего разрешения.
- «Отозвать разрешение» требует отдельного подтверждения с device/command ID.
  DELETE содержит `command_id`: если разрешение сменилось, сервер возвращает409
  вместо удаления нового разрешения. История результатов сохраняется.
- Отзыв блокирует последующие попытки отправки. Уже полученную Android команду
  или начатую установку он не отменяет. Серверная row lock сериализует проверку
  разрешения/отправку и отзыв, но не является распределённой отменой Android.
- Смена пользователя/организации/сессии изолирует queries и поздние write results.
  Pending action блокирует конкурентную запись и закрытие рабочего окна.

## Как работает доставка

Сначала API коммитит grant в PostgreSQL. Затем bounded Redis Pub/Sub сигнал
будит worker, которому принадлежит Android socket. Worker повторно читает
tenant-owned signed grant, проверяет текущий command ID, активное устройство,
срок и Android/org принадлежность socket. Отправка привязана к captured session;
replacement socket не получает ранее подготовленную команду.

Внутренний `_ota_recovery_wake` не пересылается Android и не даёт новых прав.
APK получает существующий `OTA_UPDATE`. URL managed APK строится из origin
аутентифицированного socket; HTTP origin оператора и Redis payload не выбирают
маршрут скачивания. TTL команды — min180 s/остаток разрешения. Publish и
worker read/send ограничены отдельными3 s deadlines.

Если Redis/worker недоступен, grant остаётся в PostgreSQL. Уже существующий
reconnect recovery path продолжает работать; silent grant loss не изображается
успехом. Потеря всего server/DB/storage либо отсутствие любого доступного
Android маршрута не устраняется одним retry. Durable multi-replica catalog,
production signer и fleet acceptance остаются отдельными gates.

## Принятый canary и оставшиеся границы

2 октября remote `auto-ph-013` получил managed APK1.2.40/10240 вместо1.2.30/10230:
live send13:11:37.922 UTC, post-replacement receipt13:11:59.248 UTC, свежий
heartbeat13:12:00.359 UTC. Использован существующий pilot debug artifact10240,
данные приложения не очищались; normal channel/latest aliases не продвигались.
Это **один адресный canary**, не массовая приёмка и не новый видеобенчмарк.

F33 закрыт частично: single-device workflow реализован и имеет конечный remote
install proof. Bulk rollout, verified package/flavor/signer manifest, visual
browser acceptance и 20–30-device trial остаются открытыми. На срезе18:13 UTC+5
каталог19/online14/offline5; всего3 online устройства сообщили10240.

3 октября для PH028 и10 следующих targets package/signer совместимость доказана
по exact installed APK digests и подписанным локальным baseline files. Это
ручная цепочка для этих устройств, а не появление general manifest в каталоге.
Все11 получили completed10240 и post-result heartbeat; разрешения auto-cleared.
[Новые квитанции и finite connection observations](../audits/2026-10-03/OWNED-PILOT-OTA-ROLLOUT.md).
