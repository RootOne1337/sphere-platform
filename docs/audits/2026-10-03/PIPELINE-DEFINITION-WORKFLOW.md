# F28: доказанное управление определением pipeline

**Дата:** 3 октября 2026 UTC+5; initial install/API proof2 октября21:14–21:16UTC; final UI verify21:33:20UTC.
**Baseline:** `d6be09a`; **backend:** `cc28e9b`; **UI:** `5b20955`.
**F28:** source/test/API исправлено; browser visual/keyboard **OPEN_URL_POLICY_BLOCKED**.

[Операторский контракт](../../operations/PIPELINE-DEFINITIONS.md) ·
[Evidence JSON](PIPELINE-DEFINITION-WORKFLOW-EVIDENCE.json) ·
[Frozen F28](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f28) ·
[Журнал](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[CURRENT-STATE](../../operations/CURRENT-STATE.md).

## Что воспроизведено до исправления

- UI выполнял POST toggle без обязательного `active`; установленный API вернул
  422 в `query.active`. Предыдущий preflight не создавал и не изменял pipeline.
- Create ограничивал steps 1–100, а PATCH принимал пустой массив и 101 шаг.
- PATCH не проверял уникальность ID, ссылки переходов или наличие handler type.
- Описание `null` молча игнорировалось. Поля с null, которые не nullable в БД,
  тоже молча игнорировались вместо различения пропуска и очистки.
- Операции изменения не принимали проверяемый baseline. Устаревший PATCH мог
  затереть чужую правку, toggle/delete могли изменить уже обновлённый ресурс.
- Worker читает общий timeout из текущего шаблона, несмотря на snapshot шагов.
- Строка таблицы раскрывала только краткие шаги; owned GET detail и PATCH editor
  отсутствовали. Просмотр всех params/input_schema и конфликтный workflow отсутствовали.

Новые воспроизводящие тесты на отдельном PostgreSQL: **22 failed / 8 passed / 0
errors** на исходном коде. Это 25 новых cases и 5 существующих receipt controls.
После исходного воспроизведения добавлены ещё 5 checks create/cycles/non-owner
RLS: итог focused suite **35 passed**. Связанные recovery/admission/cancel/nested
wait/connection/RLS suites: **120 passed**, а не дополнительное независимое число
исправленных проблем. Unit toggle/service: **16 passed**.

## Исправление

`cc28e9b` вводит условие `expected_updated_at`, owned NOWAIT locks, свежую ORM
identity, полную атомарность конфликта, явное description clear и одинаковые
основные graph bounds при create/edit. Фактическое изменение steps повышает
версию; повтор того же определения не выделяет лишнюю версию.

Admission одиночного и массового запуска берёт shared lock того же определения.
Изменение runtime fields запрещено при nonterminal run. Это консервативная
защита текущего worker, не новая реализация immutable timeout snapshot.
Metadata-only edit и отключение допуска новых запусков не отменяют текущие.

`d829b47` добавляет owned detail dialog, полный redacted step view, JSON editor,
проверку графа, diff изменённых полей, impact confirmation, receipt verification,
role/session isolation и сохранение dirty draft. Неизвестный исход не приводит
к blind retry. Исправлена реальная кнопка activation с explicit desired state.
Таблица получила theme-aware header и собственную горизонтальную прокрутку.

### Совместимость старых шагов

Отдельная повторная проверка выявила UI regression: metadata-only edit старого
шага без явно записанных timeout/retries отклонялся validator. Новый тест
воспроизвёл1 fail при20 controls passed. `5b20955` проверяет/нормализует defaults
только при фактическом изменении steps; metadata сохраняет исходный snapshot.
Final local suite867/types/production build passed; commit не меняет backend.

## Установленный runtime и конечный canary

Review Docker на [3015/orchestration](http://127.0.0.1:3015/orchestration)
действительно заменён на UI `5b20955`; backend image `cc28e9b` заменён отдельно.
Сборки получены из immutable `git archive` каждого source commit. Secrets не
входили в контекст/репозиторий. Image ID, container ID и UTC install timestamps
записаны в evidence. Контроль revision выполнялся также через health и compiled
UI stamp, а не только имя tag.

Проверены login/same-origin API/static asset, 401 без credentials к observability,
Prometheus backend target UP, HttpOnly/SameSite=Strict Grafana session и health,
events WebSocket upgrade/snapshot/pong. Это transport/API проверки, не браузерный
снимок нового layout.

Собственный pipeline `4ff5f7e3-f9f0-428e-97f6-cce53550df05`:

1. Создан без расписания, trigger, device target или run.
2. POST без active вернул 422; исходное состояние осталось тем же.
3. Explicit deactivate подтвердился ответом и чтением.
4. Stale PATCH/toggle/DELETE вернули 409; состояние не изменилось.
5. PATCH с steps=[] вернул 422; сопутствующее описание не сохранилось.
6. Правка steps/name/timeout и очистка description создали v2; чтение совпало.
7. Activation и окончательная deactivation подтвердились свежим чтением.
8. `GET runs?pipeline_id=...` показал **total=0**. Pipeline оставлен выключенным
   для проверки. Android-команды не отправлялись.

Canary имеет write-intent guard: после первого запуска его скрипт не допускает
автоматический повтор. В репозитории хранится sanitized receipt, не credentials.

## Проверки и оставшиеся границы

- 101 frontend suites / **867 passed**; types / production Next build passed.
- **21 новых UI cases**: activation payload/confirmation, narrow PATCH, dirty
  conflict, unknown outcome, bad receipt, double click, dirty close, invalid JSON,
  viewer, read failure и session retirement.
- **35 actual PostgreSQL cases** прошли также в новом production image с его
  Pydantic 2.9.2. Host audit venv использовал Pydantic 2.6.3; его OpenAPI export
  оказался несовместим с pinned schema formatting и не был принят как артефакт.
  Экспорт заново выполнен shipped dependencies; pinned Ruff 0.15.2 и mypy224 passed.
- Application source `d829b47` завершил все CI: [frontend37065504610](https://github.com/RootOne1337/sphere-platform/actions/runs/37065504610), [backend37065504685](https://github.com/RootOne1337/sphere-platform/actions/runs/37065504685), [Android37065504648](https://github.com/RootOne1337/sphere-platform/actions/runs/37065504648). Backend2300passed/16skipped; OpenAPI/Redis/bootstrap/RLS/security/Alembic passed. Later legacy UI correction5b20955 и documentation head требуют собственных checks.
- GitHub checks привязаны к своему SHA и состоянию на момент записи в evidence;
  прошлый d6be09a success не подменяет CI нового source/docs head.
- Input schema storage не означает input validation; общий max_retries не означает
  повтор всей цепочки. Params handlers не прошли универсальную semantic validation.
- Optional baseline condition нужен для backward compatibility; новый UI всегда
  его передаёт. Older unconditional clients не получают CAS от устаревших данных.
- N01 screenshot upload, N03 legacy RPC failures, durable audit outbox, production
  signer/rollout, video latency/quality и 20–30-device combined acceptance OPEN.
- Browser policy не обходилась другим URL/драйвером. Visual, keyboard, mobile и
  реальные permission matrix trials остаются открытыми.

Статусы остальных замечаний не изменены этим этапом. По frozen audit: **32
source findings fixed / 9 OPEN**, включая F33 PARTIAL. PR19 остаётся draft.
