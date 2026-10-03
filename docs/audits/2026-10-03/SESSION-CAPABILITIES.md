# F39 — доступ к рабочей области и управлению устройством

Дата: 3 октября 2026. Продолжение [реестра исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md),
а не новая редакция [замороженного аудита](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f39).

## Подтверждённый дефект

Боковая навигация и command palette показывали все 22 раздела независимо от
серверных прав; quick actions предлагали VPN и создание сценария пользователю
без соответствующего доступа. Это UX-дефект, не установленный обход защиты API.
Два новых component assertions на прежнем UI 77fca37 провалились; остальные12
тестов этих suites прошли. Первый запуск с отсутствующим mapped mock module
не считается доказательством и сохранён отдельно в private evidence.

Рабочий API 37415e3 до установки возвращал404 для нового capability endpoint.
Это ожидаемое отсутствие контракта, не авария работающего сервера. Readback
16:29:26 UTC подтвердил19 записей, 14 online на APK 10244. Android-команды не отправлялись.

## Контракт и реализация

- `GET /api/v1/auth/capabilities`: schema 1, user_id, org_id, актуальная роль из БД,
  отсортированные permissions из существующей `PERMISSIONS`. Ответ no-store.
  Поле role в старом JWT не расширяет полномочия; собственные guards операций
  остаются источником enforcement.
- Backend не выдаёт браузеру новую иерархию ролей. Frontend не содержит второй
  production-копии role matrix: страницы сопоставлены с permissions их API.
  У webhooks/settings профильный GET требует аутентификацию, а не новый invented permission.
- Sidebar и palette используют одну capability context; пустые группы скрываются.
  VPN/builder quick actions фильтруются по тем же правилам.
- Deep links проверяются по самому специфичному route prefix с границей `/`.
  `/scripts/builder/:id` требует write, `/scripts/:id` — read. Неизвестный маршрут
  не наследует доступ от похожего имени.
- Pending, ownership/schema error, 403, network failure и отсутствие нужного права
  имеют отдельный экран. Private feature subtree не монтируется до разрешения;
  инспектор устройства также проходит этот boundary.
- Query key включает sessionVersion/org/user/role. Чужой или malformed ответ
  отвергается. После failed refresh cached grants не используются. Опрос 60 с,
  freshness bound 90 с; focus-refetch поддержан общим QueryClient. Это не мгновенный
  push отзыва: сервер проверяет права каждого запроса немедленно, UX сверяет их
  при следующем capability read.
- Изменение серверной роли синхронизирует user store, после чего существующий
  session provider заменяет private QueryClient. Старые role-scoped данные не
  продолжают служить административным формам. Unmount очищает persistent
  inspector/palette selection; запросы не replay-ятся при смене identity.
- Единственное добавленное исключение в auth interceptor: idempotent GET
  `/auth/capabilities` может один раз обновить истёкший access через существующий
  fenced refresh. Login/logout/MFA и другие auth operations не replay-ятся.

## Просмотр и управление экраном

Viewer/script_runner могут иметь stream:read без stream:control. Single-device
карточка и отдельная страница передают explicit readOnly. Декодирование и PNG
остаются доступными, но pointer input и Android navigation недоступны даже по
статичному последнему кадру. Отзыв права между pointer-down/up отменяет жест.
Terminal/root shell/reboot требуют device:write; Logcat — device:read. Доступность
heartbeat и роли проверяется отдельно. Матричные плитки явно только для просмотра.

Это **не F34**: матрица всё ещё получает H.264 для каждого активного окна;
экономичный screenshot transport пока не реализован. XPath/F35 и реальные
quality/FPS profiles/F36 этим изменением также не объявляются готовыми.

## Проверки и границы приёмки

Исходные проверки:105 suites/982 frontend cases в Node24, types passed;
45 API/SQL/auth/stream-control cases с реальными disposable PostgreSQL/Redis
passed. Changed backend Ruff/schema mypy passed. Immutable image acceptance
и установленный API/UI фиксируются отдельно после readback. Test fixtures всех семи ролей проверяются backend-тестом на
равенство текущей PERMISSIONS; это test data, не production role matrix.

Полные role/mutation workflows остальных страниц ещё требуют отдельной
проработки. **F39 PARTIAL**: shell/deep links/identity retirement и device stream
control реализованы; every-button permission UX и fresh browser acceptance OPEN.
Исходный счётчик33 source-fixed/8OPEN не изменён. F32/F33 также PARTIAL.

Новый APK не требуется: Android10244 и текущий Tuna сохраняются. Stable signing,
normal android/dev OTA promotion10209→10244, bulk/verified manifest, 5offline и
финальный20–30-device soak остаются своими открытыми gates.

Visual/keyboard/mobile проверка текущего3015 остаётся OPEN_URL_POLICY_BLOCKED.
API/JSDOM/wire results не подменяют её; обход policy альтернативным URL/портом
не выполняется. F40 остаётся OPEN.

## Установленный результат —18:54 UTC

- Implementation [00d5ad8](https://github.com/RootOne1337/sphere-platform/commit/00d5ad8b072c490662c3c8242ac3b3b47e49b1be) установлен и в API, и в UI 3015.
- Backend45 passed внутри immutable image; 105 suites/982 frontend cases passed
  в Node24 builder с archived tests, без source replacement. Build/types passed.
- Live authenticated capability200: schema 1, owner/org/role matched, 31 grants для
  super_admin, no-store. Anonymous401. Остальные шесть ролей приняты в настоящем
  disposable PostgreSQL/HTTP, но в pilot дополнительные пользователи не создавались.
- Семь срезов18:53:54–18:54:54 сохранили14 APK 10244, heartbeat<60s и новые epochs.
  API recreation сбросил прежние epochs; доказательства непрерывного uptime нет.
- После замены только API/UI сохранены14 соседних контейнеров, Tuna и hash OTA.
  При каждом отдельном rollout сохранены15 соседей. Метрики Prometheus backend up=1.
- [CI00d5ad8](https://github.com/RootOne1337/sphere-platform/actions/runs/37137596032):
  2404 backend passed/16 skipped; workflow failed на stale generated API docs.
  Source Frontend/Android/Preview passed. Repair 729c1da экспортировал71 added/1 removed
  строки с зависимостями shipped image; image exporter check passed. Host Pydantic
  schema отличался; его export не опубликован как финальный контракт.
- Повторный CI **729c1da** ещё выполняется; полный success не заявляется.
- Runtime/helpers и их failed setup attempts хранятся приватно. Syntax/import/header
  case fixes в readback harness не являются application fixes; считаются только
  завершённые checks. [Публичное evidence](SESSION-CAPABILITIES-EVIDENCE.json).
