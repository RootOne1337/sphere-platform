# Актуальность документации

[Каталог](README.md) · [Readiness](operations/READINESS.md) · [Contributing](../CONTRIBUTING.md)

**Последняя сверка входных документов: 5 октября 2026, 16:30 UTC.** Для текущих
версий и границ live-подтверждения используйте [каноническое состояние](operations/CURRENT-STATE.md).

**5 октября, 21:11 UTC+5 — установлен EP-010 Stage B foundation:** API `d656b579`,
UI `cb5b3f91` сохранён. VPN-отчёт Android имеет независимое серверное время и
владельца сеанса; атомарная запись защищена от запоздавшего старого подключения.
После 120 с отчёт не считается свежим. Живое окно16:20 UTC:14 свежих false и5
unknown при14 online/5 offline из19. Это не проверка VPN-трафика или SLA.
Exact image444+35 tests; source CI backend2722 passed/30 skipped, frontend и
Android прошли. Сохранены45 соседей. **9 принято/41 открыто**, EP-010 ещё OPEN.
[Результат, ограничения и следующие критерии](audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION.md) · [Pinned evidence](audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json).

**Историческая установка Stage A — 5 октября, 20:31 UTC+5:** backend `66714f26`,
UI `cb5b3f91` сохранён. Список peers и pool counts теперь одинаково исключают
устаревший/future handshake, неназначенные и непривязанные peers; добавлено время
SQL-среза. Exact image: 99 VPN + 27 resource tests, mypy 231/Ruff прошли; сохранены
45 соседних контейнеров. Живой текущий VPN-каталог пуст: нули не доказывают работу
VPN на Android. Последующее окно 6×3 с: 14 online из 19, без утверждения SLA.
**9 принято / 41 открыто**: весь EP-010 ещё открыт.
[События, polling и оставшиеся источники](audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-NEXT.md) · [Image/runtime evidence](audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json).

**5 октября, 19:55 UTC+5 — EP-009 принят на живом 3015:** API/UI **`cb5b3f91`**,
gateway config **`993d9eac`** сохранён. Реальная история CPU в использованных ядрах
и памяти в GiB cgroup контейнера: окна 1/6/24 h, сбор/обновление 15 с, среднее CPU за 1 минуту.
Лимит памяти 2 GiB подтверждён; CPU quota не подменяется нулём. Host/RSS сюда не
смешиваются. 1275 frontend tests/120 suites, production Node24 build/types и 27
tests в exact API image, mypy 231/Ruff, promtool и живые queries прошли. Браузер
1600/390 px, обе темы и автоматическое обновление проверены. При замене каждого
API/UI сохранены 45 соседей; Prometheus reload без replacement всех 46.
Сохранена временная потеря 14→12→13 online; последующее конечное окно 6×3с:
14 online /5 offline из19. Это не непрерывный SLA или устранение утечки.
**9 закрыто / 41 открыто из 50**; следующий EP-010, host leak attribution, Studio
и stream+script load/soak открыты.
[Приёмка и screenshots](audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md) ·
[Pinned evidence](audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-EVIDENCE.json) · [Живой monitoring](http://127.0.0.1:3015/monitoring).

**Историческая проверка5 октября:** review UI `7c985feb` / API `51ccaa36`, gateway
`993d9eac`. EP-008 принят; product ledger8 закрыто/42 открыто отдельно от F32
и ресурсных gates. [HTTP-приёмка](audits/2026-10-05/ENTERPRISE-HTTP-METRICS.md)
связывает tests/build/install/rollback/live HTTP с пятью reviewed screenshots
и pinned git blobs. Checker проверяет integrity записанных артефактов, не live
health. [Resource recorder](audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md) COMPLETE,
241 срез; writer attribution/RAM acceptance OPEN. Source CI нового head требует
отдельного результата; старые зелёные CI не переносятся на него автоматически.

**Историческая проверка: 4 октября 2026, после перезагрузки ПК и установки в 17:14 UTC.
API/UI c1a6e79.** [Аудит диска, ОЗУ, сборки и RPC](audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md) ·
[Эксплуатационная процедура](operations/HOST-RESOURCES.md).
В образах прошли 113 наборов / 1122 frontend-теста и 186 API-проверок; отдельно
18 проверок допуска сборки. Все четыре source CI прошли. Исправлены повторные
слои зависимостей; выполнена адресная очистка. Сжатие VHD и длительная утечка ОЗУ
ещё не приняты. Remote 504 сохранён рядом с отдельным успешным PNG 200;
первое окно связи FAILED: 11→14, последующее сохранило 14 online / даты подключений.
APK 10244, Tuna и OTA сохранены. Исходный реестр: 34 исправлено / 7 незакрытых;
визуальная приёмка, FPS/задержка, длительная нагрузка и Fleet32 admission открыты.

**Исторический follow-up: 4 октября 2026, 10:06 UTC+5. API/UI9716348**, APK10244 unchanged.
[Native PNG, управление и manual Android profile](audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md).
1117 frontend / 140 API cases в образах, schema178/140. PH025/PH010 original PNG accepted;
Android/server/file hashes matched. 14online в конечном UI readback; первый remote504
и seven code1005 disconnects сохранены. Human native download/keyboard, UA2/nonroot,
full visual/latency/load/soak OPEN; original ledger34/7 не изменён.

Исторический follow-up: API **9274e50** / UI **84750e3**, [F35 XPath-инспектор](audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md).
1043 frontend и 108 API cases приняты в образах; PH010/PH025 actual root trees.
Пользовательский отказ входа/выбора воспроизведён и исправлен; 8 pointer workflows.
Original ledger: 34 source-fixed / 7 незакрытых. Browser/native UA2/nonroot/soak OPEN.
Прежние 500/504 и FAILED API fleet window 14→13 сохранены рядом с успехами;
последний UI readback сохранил 14 online и epochs в 7 срезах. Это не uptime SLA.
Historical OpenAPI: 177 operations / 139 paths; shipped API9274 schema check passed.

## Где искать текущий ответ

| Вопрос | Основной документ |
| --- | --- |
| Что подтверждено на исходниках и в последнем записанном runtime-срезе | [Актуальное состояние](operations/CURRENT-STATE.md) |
| Что реально установлено и как войти | [Local pilot](operations/LOCAL-PILOT.md), затем сверить с текущим состоянием |
| Проверка Tuna как альтернативного remote ingress | [Tuna remote stream canary](audits/2026-09-27/TUNA-REMOTE-STREAM-CANARY.md) |
| Какие проблемы остались перед 32 устройствами | [Fleet32: актуальная таблица](audits/2026-09-20/FLEET32-PREFLIGHT.md) |
| Что принимаем за готовность | [Readiness](operations/READINESS.md) |
| Какую работу делаем следующей | [Roadmap](../ROADMAP.md) |
| Чем доказано конкретное исправление | Датированный audit report и связанный evidence |
| Какой API зарегистрирован в коде | [Генерируемый каталог](api-endpoints.md) / [OpenAPI](openapi.json) |

README — вход в проект, а не дублирующий журнал всех fixes. Версии исходника,
построенного артефакта, OTA-каталога и установленного устройства — четыре разные
утверждения, их нельзя сводить к одной цифре. Версию установки обновляйте только
после post-install receipt/PackageManager evidence; CI-счётчики — по артефактам
соответствующего source commit. При противоречии используйте новый датированный
аудит контракта и заведите
[замечание](https://github.com/RootOne1337/sphere-platform/issues/new?template=documentation.yml).

## Словарь статусов

| Статус | Значение |
| --- | --- |
| Подтверждено кодом | Прослежен существующий путь; runtime последствия могут быть не измерены |
| Воспроизведено | Есть конкретный сценарий, окружение и наблюдаемый результат |
| Исправлено в исходниках | Fix и regression существуют; установка ещё не подтверждена |
| Установлено | Сверены image/APK revision, миграции и результат rollout |
| Принято | Пройден именованный сценарий на указанном числе устройств и длительности |
| Открытая проверка | Свойство ещё не доказано; само по себе это не найденный баг |
| История / проект | Состояние прежней версии либо предлагаемое решение |

`running`, «собралось», зелёный lint или доступная login page не означают
пройденный soak, исправный VPN, отсутствие повторного исполнения или production readiness.

## Как обновлять

1. Исправьте основной контракт и пример запуска рядом с изменённым кодом.
2. Для эксплуатационного дефекта запишите severity/priority, root cause, affected
   files, before/after, regression, версию установки и residual risk.
3. Обновите Fleet32/Readiness, если поменялся статус или порядок работ; README
   меняйте при изменении входа или актуального подтверждённого состояния.
4. Старое evidence не переписывайте как новый результат. Добавьте новый срез и
   ссылку; помечайте старые runtime snapshots как исторические. Сырые логи и
   конфигурации оставляйте приватными.
5. Проверьте relative links/anchors, названия команд, YAML форм и отображение
   Markdown. Каталог `docs/assets/` содержит только публичные статические ресурсы.

### Сверка 1 октября: runtime, OTA и callbacks

Обновлены README, каталог, Android guide, CURRENT-STATE, Readiness, pilot/Fleet32
указатели и codec/video canary guides. Новые [cross-layer audit и evidence](audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY.md)
разделяют code CI 8d64ca4, installed UI 8f615c6/API 8d64ca4, APK 68155c1/10240,
адресные terminal receipts и finite native/recovery measurements.
Предыдущие данные 10239 не выданы за повторный decode/CPU test 10240.
Relative links/anchors и JSON сверяются перед публикацией. Визуальная browser
review текущей сборки blocked URL policy; она не объявляется пройденной.
Эта сверка не является повторной построчной аттестацией всех архивных документов.

## Охват проверки оформления, 21 сентября 2026

Пересмотрены главная, каталог, roadmap, contribution/support/security документы,
GitHub forms/PR template/CODEOWNERS и входной путь установки. В development guide
исправлен первый запуск; исторические версии и оценки в старых отчётах явно
отделены от текущей приёмки.

**Это не повторная построчная аттестация всей документации и всех возможностей.**
Подробные модульные руководства и архивные ТЗ могут требовать сверки по мере
изменения соответствующего компонента. API-каталог генерируется из routes;
он подтверждает форму API, но не успешность всех его операций.

Публичный issue не должен содержать `.env`, ключи подписи, пароли, enrollment
tokens, дампы БД или исходные crash/log bundles. Прилагается короткое очищенное
evidence с контекстом; sensitive findings передаются по [Security policy](../SECURITY.md).

## Проверка обновлённого входа

21 сентября 2026 проверены относительные пути и anchors в изменённых документах,
ссылки на них из остальных Markdown, YAML пяти issue forms и их существующие labels,
а также SVG без внешних ресурсов и скриптов. README и каталог отрисованы через
GitHub Markdown API и визуально проверены в браузере, включая ширину 390 px.
Это проверка оформления, без изменения работающих контейнеров и APK.

На GitHub обновлены About/topics и включён private vulnerability reporting;
состояние прочитано обратно через API. Файлы оформления проходят через PR #19.
Появление новых forms в меню и обновление главной `main` требуют merge в default
branch; до этого это не выполненная проверка опубликованных форм.

### Главная репозитория и отдельный файл — разные проверки

Предыдущая проверка `9a776e7` открывала отдельный корневой README и пропустила
ошибку: добавленный `.github/README.md` получил приоритет на странице репозитория.
GitHub API `GET /repos/RootOne1337/sphere-platform/readme?ref=codex%2Fenterprise-audit-20260905`
подтвердил `path=.github/README.md`, хотя ожидался `README.md`.
Служебный документ переименован в [REPOSITORY-GUIDE.md](../.github/REPOSITORY-GUIDE.md).

После изменений входа проверяйте **страницу дерева репозитория** и поле `path`
этого endpoint на опубликованной ревизии. Просмотра `/blob/.../README.md`
недостаточно: он всегда показывает явно выбранный файл. Дополнительно проверьте
обложку, схему, якоря и переходы в документацию на самой главной странице.

После публикации `1dfe1f0` тот же endpoint вернул `path=README.md`: причина подмены
устранена. Главная дополнена картой компонентов, описанием связи/OTA, жизненным
циклом заданий, запуском, readiness и FAQ. Вводные Android/Web/architecture guides
теперь явно отделяют исторические версии и проектные оценки от текущего pilot.
Два старых якоря из ADR сохранены в архитектурном справочнике.

### Сверка 3 октября: server capabilities и роли

[Контракт и evidence](audits/2026-10-03/SESSION-CAPABILITIES.md) обновляют current
state/readiness/README/catalog/pilot/Fleet32 pointers. Frozen audit не изменён;
F39 PARTIAL,33 source-fixed/8OPEN. OpenAPI экспортируется с зависимостями shipped
image: host Python дал иной Pydantic schema и не считается acceptance exporter.


### Сверка N10: открытый viewer и восстановление после установки

Current state/readiness/README/catalog/pilot/Fleet32 обновлены до API 37bb436 / UI
00d5ad8. [N10 evidence](audits/2026-10-04/VIEWER-AUTHORIZATION-EVIDENCE.json) сохраняет
как неудачный первый cohort gate, так и принятый повторный. F39 PARTIAL, frozen audit
и исходные counts сохранены. [F34 план](audits/2026-10-04/MATRIX-PREVIEW-PLAN.md) —
проект будущего native/server/UI transport, а не установленная возможность.

### Сверка F39: действия реестра и установленный веб

Входные документы и Fleet32 указывают на UI **81d065a** / API **37bb436**.
[Контракт и проверки](audits/2026-10-04/DEVICE-ACTION-PERMISSIONS.md) разделяют
9 воспроизведённых отказов прежнего интерфейса, 997 тестов собранного веб-образа,
73 проверки неизменённого API-образа и семь срезов после установки.
14 устройств с APK 10244 сохранили даты соединений; соседние сервисы, Tuna и OTA
не заменялись. [Публичное evidence](audits/2026-10-04/DEVICE-ACTION-PERMISSIONS-EVIDENCE.json)
содержит ревизии, времена установки/проверки и ограничения. Это не повторная
аттестация архивных документов или непрерывного uptime. F39 остаётся PARTIAL;
восемь незакрытых пунктов включают три частично выполненных, frozen audit не изменён.


### Сверка F39: установленный UI форм групп и локаций

Текущие указатели обновлены до API **37bb436** / UI **922f479**, срез 4 октября 2026, 02:04 UTC+5.
[Отчёт](audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS.md) и
[evidence](audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS-EVIDENCE.json) отделяют
исходники, собранные образы, CI и конечный runtime. Предыдущие registry/N10 receipts
не переписаны. F39 PARTIAL; восемь незакрытых включают три PARTIAL, frozen audit сохранён.
