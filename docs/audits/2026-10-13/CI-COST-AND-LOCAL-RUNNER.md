# Стоимость CI и выполнение проверок на своей машине

Дата сверки: 13 октября 2026, Asia/Yekaterinburg.
Статус: локальный исполнитель регрессий проверен; GitHub self-hosted runner не установлен. Полный перенос CI ещё не принят.
Текущая установка продукта: [WORK-STATUS](../../operations/WORK-STATUS.md).

## Проверенное локальное выполнение 13 октября

Три запуска на Windows привязаны к одному точному коммиту
[`f23845ce`](https://github.com/RootOne1337/sphere-platform/commit/f23845ceb9a1a53e14946ebc4ece14a57a892523).
Результат опубликован через Commit Status API и затем прочитан обратно с теми
же SHA, context, state и ID. Это реальные локальные проверки, а не перенос
чужого зелёного статуса на новую ревизию.

Для более нового установленного API [`b65b0b54`](https://github.com/RootOne1337/sphere-platform/commit/b65b0b5469510f9c0c94d5242234bdba43570c77)
выполнены отдельные локальные проверки: frontend 2295 passed / 157 suites,
backend 3958 passed / 1 skipped, Android ordinary 4284 passed / 12 skipped
и direct/planar/continuous 2158 passed / 6 skipped. Все три GitHub context
прочитаны обратно как success для этого SHA. Android wrapper завершился с
exit 0; оба временных каталога отсутствуют, итоговый JUnit ZIP сохранён.
Ниже таблица предыдущего `f23845ce` оставлена с собственной ревизией.

| Локальный профиль | Результат | Контекст GitHub |
| --- | --- | --- |
| Frontend | 2295 тестов, 157 suites; type check и вспомогательные проверки | `Sphere Local / Frontend regressions` |
| Backend | 3921 passed, 1 skipped, 383 subtests; свежие изолированные PostgreSQL/Redis, миграции, RLS, coverage 81,77% | `Sphere Local / Backend regressions` |
| Android ordinary | 4264 passed, 12 skipped; четыре dev/enterprise Debug/Release варианта | `Sphere Local / Android unit tests` |
| Android direct/planar/continuous | 2148 passed, 6 skipped; два Debug-варианта | тот же Android context |

Артефакты и сырые логи остаются локально в `.local-pilot/local-ci/runs`.
На GitHub видны commit statuses с итогом и числом тестов; они не создают
Actions jobs с полным облачным интерфейсом логов. Отдельный scheduled/self-hosted
runner ещё не зарегистрирован. Интернет нужен для публикации результата.

В 11:33 Asia/Yekaterinburg включена отдельная локальная очередь для
`refs/heads/codex/enterprise-audit-20260905`: опрос раз в 60 секунд, три профиля
последовательно. Её первоначальный completed SHA — только реально проверенный
`b65b0b54`; более новый опубликованный локальный коммит запускает новые проверки.
Удалённый head без совпадающего локального head и fork PR не допускаются.
Процесс и занятый lock проверены. Автозапуск после reboot и независимый lifetime
не гарантированы; временное разрешение работать с предупреждением C: ограничено
в конфигурации 24 часами. Это локальная очередь, GitHub runner не зарегистрирован.

Android-тесты закончились успешно, но первая завершающая очистка исполнителя
отказала на оставленных Gradle-каталогах. Исправление сохраняет JUnit ZIP,
проверяет пути и удаляет только два каталога конкретного завершённого запуска.
Проверены длинные Windows-пути, запрет redirects и сохранение общих кешей.
Для исходного запуска выполнена отдельная сверка и очистка; этот технический
сбой исполнителя не переименован в успешный первый exit code.

В исполнителе есть одна очередь тяжёлых задач, разрешённая локальная ветка,
проверка совпадения опубликованного SHA, свежие каталоги вывода и ограничение
истории до 10 запусков / 256 MiB отчётов. Публичные fork PR не запускаются
на личном ПК. Исходники Android проверяются по содержимому до и после тестов.
Текущая активация очереди и более новые запуски фиксируются в
[WORK-STATUS](../../operations/WORK-STATUS.md), а не предполагаются по наличию кода.

Cloud workflows пока включены: packaging, Linux parity, security и
signature/JNI gates требуют отдельного эквивалентного локального приёмочного
прогона. Три локальных зелёных контекста не означают, что все эти границы уже
перенесены или что проверена более новая ревизия.

## Что установлено по факту

GitHub API вернул для `RootOne1337/sphere-platform` `private=false`,
`visibility=public`. В трёх основных workflows задан стандартный
`runs-on: ubuntu-latest`. Зарегистрированных self-hosted runners нет.
Это фактическая текущая конфигурация, а не предположение о тарифе аккаунта.

В актуальной документации GitHub стандартные hosted runners в публичных
репозиториях и self-hosted compute указаны как бесплатные. Квота 2000 минут
GitHub Free относится к облачным запускам private-репозиториев. Следовательно,
текущие стандартные CI jobs именно этого публичного проекта не должны уменьшать
этот лимит. Larger runners имеют отдельные условия. Основания:
[billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage),
[описание self-hosted](https://docs.github.com/en/actions/concepts/runners/self-hosted-runners).

Прямой запрос account billing usage в доступной сессии не дал пригодного
readback. Остаток квоты, наличие платёжного метода и действующие budgets неизвестны.
Не заявляется ни исчерпание квоты, ни сумма счёта, ни отсутствие расходов
в остальных репозиториях аккаунта. Видимость проекта и финансовые настройки
не изменялись. Cloud CI не отключался.

## Артефакты, cache и деньги — разные измерения

Read-only API-срез 12 октября, 22:00:08 UTC:

| Измерение | Результат | Граница |
| --- | --- | --- |
| Actions cache | 5 записей, 712 946 514 логических байт | Это текущий cache, не начисленный счёт |
| Artifact API | Всего указано 2108 записей, прочитана первая страница из 100 | Это неполный inventory |
| Неистёкшие artifacts этой страницы | 100 записей, 6 768 707 043 логических байта | Нельзя выдавать за общий размер или billable usage |
| Account usage/budgets | Не получены | Unknown, не ноль |
| Удаление remote artifacts | Не выполнялось | История и доставка сохранены |

Условия хранения рассматриваются отдельно от runner compute; inventory API
не доказывает применимость оплачиваемого SKU. Нельзя применять общую allowance
private-аккаунта к публичному проекту без подтверждения условий и billing readback.
Встроенный job log также отличается от файла, намеренно загруженного как artifact.
Авторитетные определения: [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Старый ответ форума не используется как гарантия тарифа на октябрь 2026.

Сокращение retention снижает будущий объём хранимых данных; оно не заменяет
измерение начислений. Новая политика должна сохранять текущую установленную
сборку, проверенный rollback и отчёты, на которые ссылаются immutable receipts.
Удаление всех artifacts или workflow runs не является планом экономии.

Для контроля возможных платных SKU предназначены account budgets с явным
режимом остановки; одни email alerts не останавливают расходы. Это настройка
аккаунта, в данном аудите она не применялась.
[Инструкция GitHub](https://docs.github.com/en/billing/how-tos/set-up-budgets).

## Почему текущие проверки повторяются

Backend и frontend запускаются на изменениях PR без фильтра компонентов.
Android имеет `paths`, но у события pull_request они проверяют накопленный diff
всего PR. В PR19 Android менялся раньше, поэтому последующий коммит только с
вебом также запускает полный Android workflow. Отсутствие APK-изменений в одном
последнем коммите не означает отсутствие Android в diff PR.

Backend проверяет SQL/Redis, миграции, RLS, lint, security и shipped image.
Frontend выполняет React-тесты, type-check, production build, HTTP/asset probes
и packaging. Android проверяет ordinary/signature/JNI gates и несколько
экспериментальных профилей. Это полезные разные границы, но их повтор на каждом
мелком шаге не всегда даёт новую информацию.

В новом исходнике Android добавлены такие же `concurrency` и
`cancel-in-progress`, как у backend/frontend. Последующие запуски одной PR/ref
не должны одновременно продолжать устаревшие Android jobs. Сами тесты,
подписи и JNI-проверки не исключены. Запуски, начавшиеся до появления группы,
не объявляются автоматически отменёнными.

Следующая оптимизация — отдельная небольшая проверка applicability для точного
source tree, dependencies, action contract и build profile. Если переиспользуется
ранее проверенный результат, необходимо сохранить producer SHA/run/attempt,
tree fingerprint, проверку доверия и причину reuse. Старый APK или image нельзя
переименовывать как новую протестированную сборку. Данный механизм пока не внедрён.

## Как локальные результаты остаются в GitHub

| Способ запуска | Вычисления | Что видно в GitHub |
| --- | --- | --- |
| Обычный GitHub-hosted Action | Runner GitHub | Run, jobs, logs, checks на commit/PR |
| GitHub self-hosted Action | Наша машина | Те же run/jobs/logs/checks, привязанные к SHA |
| Ручной pytest/Jest/Gradle в терминале | Наша машина | Автоматической проверки у SHA нет |
| Собственный local orchestrator + Checks/Status API | Наша машина | Только то, что корректно опубликовал reporter |

Self-hosted — готовый штатный runner GitHub, поэтому не требуется заново писать
диспетчер и протокол статусов. Интернет нужен для назначения работы и передачи
результатов. При offline runner job ожидает исполнителя; ожидание не означает
успешный тест. Native Windows runner допустим, но наши Docker service/container
jobs требуют Linux и Docker:
[официальные требования](https://docs.github.com/en/actions/reference/runners/self-hosted-runners).

Каждая проверка сохраняет точный checkout SHA и состояние success/failure/
cancelled. Summary содержит команды, profile, число тестов, skips, source
fingerprints и ссылки на отчёты. Отчёт JUnit может быть artifact, а annotations
и текстовый job summary — отдельным представлением. Green check не заменяет
фактический лог и не означает, что APK установлен или Android действие исполнено.

Если cloud compute впоследствии выключается, автоматического fallback на платный
runner быть не должно. Выключенный локальный компьютер означает queued/failed
job по явному timeout, а не скрытый cloud запуск. Переключение требуемых checks
согласуется с branch protection; удалять checks ради зелёной PR нельзя.

## Требования к локальному исполнителю

Текущий ПК уже обслуживает Android, Docker и браузер; C: имеет ограниченный запас.
В этой поставке установка API действительно останавливалась при нехватке
headroom. Поэтому просто заменить `ubuntu-latest` на `self-hosted` здесь недостаточно.

Предлагается один отдельный Linux execution environment и последовательная очередь.
Предпочтителен отдельный хост; вариант на этом ПК допускается только после
измеренного свободного места и ресурсного допуска. Docker daemon тестов должен
быть отделён от рабочего проекта. Test checkout не совпадает с живой рабочей копией.

| Контракт | Требование до активации |
| --- | --- |
| Доверие | На публичном проекте непроверенный fork/PR не исполняется на личном хосте |
| Изоляция | Одноразовое окружение, минимальный пользователь, без личных директорий и рабочего Docker socket |
| Подписывание | Disposable CI key отделён от ключа установленного APK |
| Ресурсы | Один тяжёлый job; CPU/RAM/disk/Windows commit измерены до запуска |
| Приоритет | Видеопоток и эмуляторы имеют запас ресурсов; сборка не конкурирует бесконтрольно |
| Диск | Квоты cache/output, per-job budget, reserve и удаление только собственных временных путей |
| Cleanup | Точные IDs test containers/volumes, отсутствие blanket prune |
| Перезапуск | Старый job получает cancelled/failed; неизвестный результат не превращается в success |
| Отчёты | SHA, workflow, profile, exit code, elapsed time, test counts и JUnit |
| Provenance | Digest сборки, producer run/attempt, contract и dependency hashes |
| Доставка | Tests, packaging, публикация и установка — разные этапы |
| Maintenance | Пинованные tools/actions, обновление runner, ограниченный retention |

Нужны раздельные bounded budgets для Gradle, npm, Python wheels, build layers,
временных артефактов и retained rollback. Сумма этих budgets должна быть
согласована с физическим запасом C:, а не только с логическим Docker `df`.

## Практическая последовательность

1. Сверить тип репозитория, runners, paid SKU и budgets; не исходить из числа
   «2000» без привязки к фактически оплачиваемому использованию.
2. Измерить продолжительность jobs, причины повторов, cache и artifact inventory.
3. Сохранить cloud validation и конкретные receipts текущей установки.
4. Настроить отдельное execution environment, reserve, квоты и cleanup.
5. Подключить штатный ephemeral runner к одному trusted workflow без доступа
   к живому проекту, сравнить результаты с известным CI producer.
6. Проверить offline, reboot, cancelled job, timeout, cache corruption и cleanup.
7. Подтвердить видимость checks/logs/JUnit на конкретном SHA и поведение PR gates.
8. После этого переключать routing; платный fallback требует отдельного решения.

Ни переключение на локальный CI, ни account financial policy здесь не объявлены
выполненными. Текущий результат — проверенные факты, контракт миграции и
исправление повторного импорта уже проверенных backend images:
`scripts/pilot/install_reviewed_backend.py`, source `db8e01ed`.
74 локальных проверки установщика и 192 subtests прошли; successful API install
использовал существующий точный image без нового `docker image load`.
Этот фикс не доказывает причину всего старого footprint Docker.
