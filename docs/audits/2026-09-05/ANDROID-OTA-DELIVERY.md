# OTA: самостоятельное обновление Android

**13 сентября 2026 · AUD-104–106 · High operational · история приёмки APK 1.2.3.**

Поздняя source-проверка конкурентного каталога (24 сентября) вынесена в
[AUD-143](../2026-09-24/OTA-CATALOG-CONCURRENCY.md): одновременные публикации теперь
сериализованы и сохраняются атомарно. Это исправление исходников PR #19, не
утверждение о live deployment или многосерверной приёмке.

Актуальная APK — **1.2.4 / `fdd26c5`**, оба Android уже обновились. Native обрыв,
параллельные команды, staging cleanup и повторный reboot описаны в [AUD-107](ANDROID-OTA-RECOVERY.md).
Числа/каталог/хеши ниже относятся к исторической приёмке 1.2.3.

[Аудит](AUDIT-REPORT.md) · [Автозапуск](ANDROID-BOOT-RECOVERY.md) · [Стенд](../../operations/LOCAL-PILOT.md)

## Подтверждённый дефект

`UpdateCheckWorker` возвращал success на любой неуспешный HTTP ответ.
Короткий 503, rate limit 429 или 401 считались завершённой проверкой: следующая
периодическая попытка могла произойти только через шесть часов. Refresh token
выполнялся вне try/retry, management URL читался до suspend refresh и мог
устареть при восстановлении маршрута. Cancellation внутри OTA перехватывалась
как обычный отказ. Версия из ответа не сравнивалась с установленной APK.

## Fix и regression

Проверка выполняется на IO dispatcher. Refresh входит в retry policy, адрес
читается после refresh. HTTP failures и некорректная metadata возвращают retry,
coroutine cancellation пробрасывается. Явное отсутствие обновления и уже
установленная/более старая версия завершаются без вызова установщика.
WorkManager использует существующий exponential backoff от 30 s, с ограничениями
Android по сети и расписанию; это не обещание точного времени обновления.

Affected files: `workers/UpdateCheckWorker.kt`, его новый production-class test,
`android/version.properties` (**10203 / 1.2.3** для следующего кандидата).
**До: 9 failures / 14 cases. После: 14 worker cases pass, полный dev JVM suite
547 tests / 40 suites / 0 failures/errors/skips.** HTTP fixtures используют
реальный OkHttp request/response path; отдельно проверяются refresh race,
HTTP 401/429/503, срыв сети/установки, stale version, size limit и cancellation.
[Evidence](evidence/android-ota-worker-summary.json).

## Что проверено на настоящем Android

Точный прежний `pm install -r -t <app-private-apk>` запущен через собственный
`su` от UID APK второго Android. Установка совместимой копии того же package
завершилась `Success` за 0.359 s без диалога. Проверяемая копия удалена.
Гипотеза о недоступности private path на этом ROM **не подтвердилась**;
ненужного изменения установщика по этой гипотезе не внесено.
[Component evidence](evidence/native-ota-root-installer-20260913.json).

Этот компонентный тест инициирован через ADB и не считается OTA-доставкой.
На момент начала проверки серверный каталог пуст, download endpoint для APK
отсутствует. Свежий локальный файл и alias LATEST сами по себе не публикуют
обновление. Нужна отдельная приёмка: авторизованная выдача файла сервером,
скачивание внутри APK, замена версии, самостоятельный старт и реальные команды.

## AUD-105: авторизованная выдача APK сервером

В каталоге можно было записать URL, но сам backend не имел download endpoint
для APK. Новый `GET /api/v1/updates/artifacts/{sha256}` принимает Bearer JWT
устройства через существующую проверку активной identity. Файл должен быть
опубликован в каталоге, находиться в `artifacts/<sha256>.apk` рядом с каталогом,
не быть symlink и соответствовать SHA/размеру при публикации. Неопубликованный
файл не выдаётся; ответ `private, no-store` не разрешает публичное кеширование.

В release metadata допускается точный относительный путь
`/api/v1/updates/artifacts/<sha256>`. `/latest` преобразует его в HTTPS URL
с текущим request host. Смена ingress не требует переписывать download hostname
каждого релиза. Прежние внешние HTTPS metadata остаются совместимы, но APK
допускает скачивание только с management host.

Affected files: `backend/api/v1/updates/router.py` и HTTP regression tests.
**2 before failures / 24 cases → 56 passed** после fix, включая настоящий
PostgreSQL/Redis, device JWT/refresh и tenant HTTP/WS checks.
[Evidence](evidence/ota-artifact-api-summary.json).

Развёртывание: оператор сначала помещает проверенный immutable APK в persistent
`artifacts` directory рядом с `SPHERE_UPDATES_PATH`, затем регистрирует release
через существующий super-admin `POST /updates/`. Значения SHA, package/signing
identity и versionCode должны относиться к этому APK. Создание локального файла
без публикации metadata обновление не включает. Обычный `/tmp` внутри контейнера
не является persistent storage; pilot использует отдельный directory bind mount.
Полная native-доставка и сохранение каталога после container recreation
проверяются следующими шагами, отдельно от HTTP regression suite.

## AUD-106: localhost в URL из каталога через настоящий туннель

Native final check выявил дефект интеграции AUD-105: `/latest` возвращал
`https://localhost/api/v1/updates/artifacts/...`. Remote gateway принудительно
заменял Host на localhost, поэтому backend формировал непригодный для Android URL.
Командные OTA trials использовали проверенный внешний URL явно и не могли
подтвердить корректность каталожного URL. Ошибка найдена отдельной проверкой.

`infrastructure/nginx/remote-pilot.conf` теперь сохраняет incoming Host;
X-Forwarded-Host по-прежнему перезаписывается gateway. Regression запускает
настоящий Nginx с production config и отдельным echo upstream в isolated internal
Docker network. Старый config возвращает localhost — тест падает. После fix
сохраняются primary/recovered host, scoped forwarded header и входной port.
Compose isolation suite проходит вместе с ним. Затем только новый public-gateway
проверен `nginx -t` и reload; `/latest` через настоящий tunnel вернул текущий
management host, 12/12 команд прошли. [Evidence](evidence/ota-ingress-host-summary.json).
Native полная цепочка проверена на HTTPS 443; нестандартный порт всей proxy chain
не принят этим тестом, который проверяет порт только на remote gateway hop.

## Native OTA на двух устройствах

APK **`a1a40ff`, 1.2.3-dev / 10203**, 8,383,485 bytes, SHA-256
`44126e952376667a8f8cb7bcfd2923ac4343ecfa0a9e5eda6ff79008e2f826ee`.
Backend нового pilot: `c2d412f`; gateway Host fix: `985e4fc`.

1. Проверенный файл помещён в отдельный `.local-pilot/updates/artifacts/`.
   Backend получает persistent bind mount и `SPHERE_UPDATES_PATH` вне `/tmp`.
   Канареечный release сначала исключён из обычного android catalog.
2. Второй APK получил `OTA_UPDATE` по своему существующему WebSocket. Скачивание
   выполнено **внутри APK** с авторизацией, затем SHA и собственный `su` install.
   Реально установленная версия изменилась **10202 → 10203**, хеш совпал;
   новый процесс выполнил команду через **6.641 s**. Windows task отключена,
   ADB install/app-launch команд и ручных нажатий нет. Первый APK продолжал работу.
3. Backend-контейнер пересоздан с тем же образом. Каталог сохранён побайтно,
   авторизованная выдача APK сохранила SHA, оба устройства снова отвечают.
   Это persistence конкретного bind mount; конкурентность JSON ещё не проверена.
4. Опубликован обычный release **android/dev**, затем первый APK тем же OTA-путём
   обновился и выполнил команду через **10.125 s**. Второй процесс сохранён.
   Canary metadata удалена после успешной приёмки. В каталоге **1 release**.
5. После OTA выполнен reboot второго Android при отключённом Windows task:
   ОС сама запустила `BootRecoveryJobService`, команда вернулась за **22.000 s**,
   новые регистрации отсутствуют, signed cache v9 и installed SHA сохранены.
6. Проверен настоящий `/latest` через внешний tunnel: для 10202 доступно обновление
   с текущим HTTPS host, для 10203 обновления нет. На обоих Android WorkManager DB
   содержит ENQUEUED `UpdateCheckWorker`, interval 21,600,000 ms / backoff 30,000 ms.
   Затем **12/12 команд** и настоящие журналы на обоих, SHA обоих installed APK совпал.

[Полные native evidence и расписание](evidence/apk-ota-native-rollout-20260913.json) ·
[Artifact manifest](evidence/apk-a1a40ff-manifest.json).
Dev JVM: 547 tests; signed dev/enterprise: **по 61 selected tests**, без ошибок.
Указатель LATEST обновлён после этой приёмки.

**Точные границы:** установка проверена серверной командой; полный шестичасовой
интервал штатного worker в native-тесте не выжидался. Расписание проверено read-only,
worker metadata/retry проверены production-class tests. Каждая будущая сборка
требует публикации проверенного файла и metadata; git commit или замена локального
LATEST не обновляют парк сами по себе. Не принята безусловная установка на любой
Android/любой package/flavor и массовый rollout.

CI `c2d412f` дошёл до проверки generated API docs и обнаружил устаревший export;
`f6b64d3` обновил OpenAPI/catalog, локальный `--check` проходит. Более поздний PR head
проверяется отдельно; прошлый полный зелёный архив `8d93e48` не заменяет его CI.

## Residual risk

- Native root test принят только на данном Android 9 с уже разрешённым `su`
  для приложения. Без таких полномочий PackageInstaller может требовать
  `STATUS_PENDING_USER_ACTION`; root на устройстве не равен разрешению каждому UID.
- Download interruption/cleanup и параллельные попытки исправлены в [AUD-107](ANDROID-OTA-RECOVERY.md);
  новая native-приёмка описана отдельно. Signer/package checks и staged fleet rollout
  ещё открыты. Source-level конкурентная запись JSON-каталога исправлена в AUD-143,
  но не установлена в live pilot; механизм поддерживает только процессы, совместно
  использующие один узел и файловую систему с совместимыми lock/atomic-replace semantics.
  Сохранность каталога и файла при replacement проверена только для pilot bind mount.
- Шестичасовой штатный период остаётся; автоматическое повторение короткого
  отказа исправлено, push-публикация на весь fleet пока не принята.
- Потеря всех доступных серверных маршрутов не устраняется одним OTA worker.

Контракты Android: [WorkManager retry](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work) ·
[PackageInstaller result](https://developer.android.com/reference/android/content/pm/PackageInstaller).
