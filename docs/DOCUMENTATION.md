# Актуальность документации

**Проверенная установка:** UI `d70f55c6` / API `9ad3481c`.

[Каталог](README.md) · [Readiness](operations/READINESS.md) · [Contributing](../CONTRIBUTING.md)

**Последняя сверка статусов и навигации:9октября2026 (UTC+5).**
Действующие источники: [WORK-STATUS](operations/WORK-STATUS.md),
[STATUS-REGISTRY.json](operations/STATUS-REGISTRY.json),
[CURRENT-STATE](operations/CURRENT-STATE.md). Датированные аудиты остаются
неизменяемыми receipts; последний большой [crosscheck](audits/2026-10-09/CHAT-CODE-RECONCILIATION.md)
не выдаётся за новую установку или fleet acceptance.

## Покрытие и проверка

[Инвентарь документации](operations/DOCUMENT-INVENTORY.json) классифицирует все
tracked Markdown по назначению: действующий указатель, руководство, исторический
receipt, ADR, проектное ТЗ или сопутствующий документ. Статический scan проверяет
локальные пути действующих guides; он не исполняет команды runbooks и не доказывает
семантику каждой строки, актуальность сторонних сайтов или production readiness.
Глубокая сверка runtime/source относится к конкретным требованиям STATUS-REGISTRY.
Исторические specs и audits не переписываются в качестве действующих возможностей.

```powershell
python -m scripts.check_documentation_status
python -m unittest discover -s tests -p test_documentation_status.py
```

Checker сверяет 50 уникальных EP, исходные criteria/dependencies,9 evidence-backed
closures, отдельные legacy7, ссылки требований, hashes frozen closure receipts,
покрытие tracked Markdown и обязательные current pointers. Его успех означает
consistency записанных документов, а не исправность Android. После нового
Markdown обновите inventory; после установки обновите runtime observation/evidence.
Действующий installed receipt также связан с реестром normalized SHA-256,
точными UI/API revisions и признаками installation/finite acceptance; новая
доставка проверяется независимо от списка прежних completedCorrections.
После установки обновляйте строку `**Проверенная установка:** UI … / API ….`
в основных входных документах, WORK-STATUS, LOCAL-PILOT и REVIEW-GATEWAY.
Checker требует одну точную строку в первых 40 строках каждого такого документа,
сверенную с установленным receipt через STATUS-REGISTRY. Датированные упоминания
версий в истории разрешены; эта проверка не доказывает семантику всей прозы.

## Порядок закрытия и supersession

У полного EP должны быть выполнены все его acceptanceCriteria; для частично
выполненного требования храните acceptedScope и remaining, не ставьте ACCEPTED.
Source/test/install/live/fleet — разные стадии. CI надо ссылать на exact source SHA.
Source clock receipt1577e01e хранит прежнюю source-only границу. Новая
[доставка60be6ecd](audits/2026-10-09/STUDIO-CLOCK-INSTALLED-ACCEPTANCE.md) принята
отдельно: completedCorrections содержит её normalized SHA и точный installed SHA.
Исторический source receipt не переписывается ради нового installed статуса.
Исторический UI86354350 имеет отдельный [installed receipt](audits/2026-10-09/STREAM-DIAGNOSTICS-INSTALLED-ACCEPTANCE.md):
диагностика и её компоновка приняты в конечном scope. Последующая backend-only
[доставка API d720232e](audits/2026-10-09/CONTINUOUS-SERVER-TIMINGS-INSTALLED.md)
сохраняет UI и подтверждает повторный idle failure; причина остаётся OPEN.
Последующий [native pilot receipt](audits/2026-10-09/DIRECT-PROBE-PILOT.json)
связывает текущие UI d70/API9ad с восстановленным APK и выключенным probe.
`browser.finiteAccepted` относится только к обычному read/first-frame return;
`directPilot.connectivityAccepted=false` сохраняет отказ прямого соединения.
Отрицательный pilot outcome не является закрытием пункта или приёмкой задержки.
391/392/393 Markdown в датированных snapshots относятся к своим source revisions;
действующее покрытие берётся из DOCUMENT-INVENTORY.json.
Каждая приёмка указывает версии, время, устройства, сценарий, длительность и
ограничения; unknown/rejected outcomes сохраняются рядом с успехами.

Frozen backlog5октября, prior crosscheck JSON и receipts не меняйте при закрытии:
добавляйте новый receipt и меняйте действующий registry. Hash исторического
snapshot относится к его исходным байтам; изменение активного guide после него
не означает corruption. Новая более узкая canary не закрывает широкий parent EP.
Closed workflow из чата храните как CHAT-ID со ссылкой на parent EP и остатком.
Числа разных аудитов не складывайте и не deduplicate без отдельного доказательства.

## История обновления входных документов

Подробная runtime история прежнего входного документа сохранена в
[его git версииf79de047](https://github.com/RootOne1337/sphere-platform/blob/f79de04725deebd1c04a45bb2038ca145c42a1d3/docs/DOCUMENTATION.md).
Ниже старые датированные записи сохраняют свой scope.

## Где искать текущий ответ

| Вопрос | Основной документ |
| --- | --- |
| Что подтверждено на исходниках и в последнем записанном runtime-срезе | [Актуальное состояние](operations/CURRENT-STATE.md) |
| Что реально установлено и как войти | [Local pilot](operations/LOCAL-PILOT.md), затем сверить с текущим состоянием |
| Проверка Tuna как альтернативного remote ingress | [Tuna remote stream canary](audits/2026-09-27/TUNA-REMOTE-STREAM-CANARY.md) |
| Какие проблемы остались перед 32 устройствами | [Fleet32: актуальная таблица](audits/2026-09-20/FLEET32-PREFLIGHT.md) |
| Что принимаем за готовность | [Readiness](operations/READINESS.md) |
| Какую работу делаем следующей | [Действующий реестр](operations/WORK-STATUS.md), затем [Roadmap](../ROADMAP.md) |
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
