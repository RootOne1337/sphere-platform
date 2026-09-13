# OTA: самостоятельное обновление Android

**13 сентября 2026 · AUD-104 · High operational · worker исправлен, полная доставка проходит приёмку.**

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

## Residual risk

- Native root test принят только на данном Android 9 с уже разрешённым `su`
  для приложения. Без таких полномочий PackageInstaller может требовать
  `STATUS_PENDING_USER_ACTION`; root на устройстве не равен разрешению каждому UID.
- Download interruption/cleanup, конкурентная установка, signer/package checks,
  сохранность каталога между контейнерами и staged fleet rollout ещё открыты.
- Шестичасовой штатный период остаётся; автоматическое повторение короткого
  отказа исправлено, push-публикация на весь fleet пока не принята.
- Потеря всех доступных серверных маршрутов не устраняется одним OTA worker.

Контракты Android: [WorkManager retry](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work) ·
[PackageInstaller result](https://developer.android.com/reference/android/content/pm/PackageInstaller).
