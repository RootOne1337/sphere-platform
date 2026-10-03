# F32 — подтверждённые цели и результаты VPN-команд

Дата: 3 октября 2026, Asia/Yekaterinburg. Baseline: `a9664d8`.
API: `3461bf6` → `8cd5cf0`; UI: `a2c4f02`; test-only correction: `3ac818f`.

[Контракт оператора](../../operations/VPN-CONTROL-OUTCOMES.md) · [Evidence JSON](VPN-CONTROL-OUTCOMES-EVIDENCE.json) · [Реестр](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Текущее состояние](../../operations/CURRENT-STATE.md) · [API](../../api-reference.md)

## Результат и область

Изменения установлены в проверочный веб [3015/vpn](http://127.0.0.1:3015/vpn).
Главная VPN-страница показывает адресное подтверждение и результат для каждого
устройства. Нет автоматического повтора операции с неизвестным исходом.
Backend валидирует всю выбранную группу до обращения к провайдеру или sender.

Это доработка существующих control contracts, без интеграции нового VPN,
Amnezia или Windows-агента. Android + сервер остаются архитектурой проекта.
**F32 PARTIAL:** результаты исправлены, но browser/keyboard/mobile и остающаяся
durable reconciliation приёмка открыты. Счётчик fully-fixed не увеличен:
**33 source-fixed / 8 OPEN**, включая F32 и F33 PARTIAL.

## Доказанные проблемы

1. UI отправлял `{enabled:false}`, а schema молча игнорировала поле и подставляла
   `action="enable"`. Это была ошибочная смена намерения, а не корректный disable.
2. Пустой список rotation означал все назначенные peers организации.
3. Kill-switch не имел полного owned-target preflight; поздняя ошибка могла
   возникнуть после вызова sender для предыдущего устройства.
4. Исключение при rotation/sender прерывало весь batch; operator не видел
   подтверждённую стадию отдельных целей.
5. No-op publisher и legacy `vpn_killswitch` envelope не совместимы с имеющимися
   Android `VPN_CONNECT/DISCONNECT/RECONNECT`. Успех API не доказывал работу APK.
6. UI скрывал результаты, допускал повторное нажатие и не отделял router assignment
   от применения Android-конфига.

Исходный backend regression run: **17 cases, 15 failures / 2 permission controls**.
Первый ошибочный harness обращался к неверному fixture app; он был исправлен до
этого baseline и не включён в число воспроизведённых продуктовых дефектов.
Четыре последующие regression cases добавлены после первоначального baseline;
для них не заявляется отдельный before run.

## Исправленный контракт

| Граница | Поведение |
|---|---|
| Selection | 1–500 уникальных UUID, все active/owned; invalid/duplicate/empty → 422, missing/foreign/inactive → общий 404 до side effects |
| Kill-switch | Explicit `action`, методы `vpnservice/iptables`; legacy `enabled` не принимается |
| Rotation | Явные targets; missing peer → `rejected`, без implicit assignment |
| Rotation receipt | `configured/rejected/unknown`, `old_ip`, `new_ip`, `revoke_confirmed`; provider errors очищены |
| Kill receipt | `submitted/not_sent/unsupported/unknown` по каждому ID; отправка не равна выполнению |
| Execution | `execution_confirmed:false` в rotate/kill; нет выдуманного Android ACK |
| Confirmation | Полные targets и влияние на связь; повторное чтение каталога; pending close/double click guards |
| Session | Actor/org/role/session cache scope; поздний callback не обновляет новую сессию |
| Recovery | Только explicit `not_sent` можно подготовить к повтору с новым подтверждением; unknown не replay |
| Assignment | Проверяется точный receipt; router config не называется установленным в APK |

Rotation остаётся последовательным двухстадийным revoke/assign. После исключения
`unknown` не доказывает отсутствие side effects. Durable reservations могут
требовать reconciliation. Preflight не является peer revision fence или
exactly-once API. Unknown guard UI действует только пока смонтирована эта страница
в этой сессии; full reload или другой браузер не сохраняют guard.

## N06 — реальная ошибка dependency ordering

Первая установленная API-сборка `3461bf6` отклоняла legacy enabled и missing action
с 422, но empty rotation получила **503** из-за отсутствия
`VPN_KEY_ENCRYPTION_KEY`: FastAPI инициализировал dependency раньше body validation.
Начальный live runner остановился на этом ответе; provider не вызывался.

`8cd5cf0` откладывает cipher/provider initialization до фактического assign/revoke.
Invalid body и owned-target rejection теперь работают без credentials.
Три regression cases используют реальную DI-цепочку, missing cipher factory и
disposable PostgreSQL. Новый production image и повторная live проба подтвердили
**empty422 / duplicate422 / foreign-or-missing404**, без provider вызова.

## Проверки исходников и сборки

| Проверка | Результат / граница |
|---|---|
| Targeted PostgreSQL/RLS | 21 cases passed; fake provider/sender, без действий на парке |
| VPN + production regressions | 159 passed на host и 159 passed в immutable API image `8cd5cf0`, без backend source mount |
| Новый UI workflow | 21 новых dialog/receipt cases и дополнительный hook catalog guard; весь frontend проверен ниже |
| Windows Node25 | До test-only correction: 103 suites / 915 passed; targeted build stamp 8 passed после correction |
| Shipped Linux Node24.21.0 | После correction: **103 suites / 916 passed / 0 failed / 0 skipped** |
| Types/build/lint | Passed; production UI из git archive, standalone; 44 прежних lint warnings |
| Backend static/schema | Ruff0.15.2 passed backend/tests; mypy225 modules; Pydantic2.9.2 OpenAPI175 operations / 137 paths, check passed |

Первый запуск packaged Node24 suite завершился **913 passed / 2 failed**:
build-stamp tests предполагали отсутствие `NEXT_PUBLIC_BUILD_SHA`. В Docker SHA
задан намеренно, компонент показывал его правильно. Test-only `3ac818f` задаёт
детерминированный frontend fixture и дополнительно проверяет mismatch warning.
Assertion не ослаблен до принятия произвольного текста.

Итоговый Node24 runner использует compiled production frontend `a2c4f02` и tests
из git archive `3ac818f`; production frontend между ними побайтово по git diff
не изменён. Test mount необходим, потому что production `.dockerignore`
исключает `__tests__`. Docker network выключен. Первый ошибочный запуск без mount
отдельно сохранён как harness failure, не как defect APK или веба.

## Установленный runtime и конечная API-проба

- API `8cd5cf0`: readiness и build revision совпали **2 октября22:59:12 UTC**.
- UI `a2c4f02`: healthy **22:50:41 UTC**, loopback `3015`;
  read-only root, dropped ALL capabilities, `unless-stopped` сохранены.
- Integration **22:59:14 UTC**: login, same-origin API, compiled UI stamp,
  static asset, unauthenticated observability401, Prometheus backend UP,
  Grafana HttpOnly/SameSiteStrict session/health, events WS snapshot/pong passed.
- 13 постоянных соседних сервисов сохранили IDs/images/StartedAt/running.
- Public frontend, APK, OTA catalog/artifacts и Tuna configuration не изменены.

Шесть live API checks: legacy enabled422, missing action422, empty rotation422,
duplicate targets422, mixed owned/missing selection404, owned disable200 с
`success:0`, двумя `unsupported` и `execution_confirmed:false`. Device metadata
и peer catalog сохранены. **Ни VPN provider operations, ни Android VPN/reboot
commands не отправлены.** Это не live Android kill-switch acceptance.

## Отдельная проблема связи и неполного обновления APK

Шесть срезов22:59:15–23:00:05UTC показали online **14,14,14,14,11,12** из19.
Online cohort нестабилен. Следующий readback вернул14, что не отменяет потери.
Сервер записал пять client-close1005; один replacement4009 учитывается отдельно.
Это не доказательство причины в Tuna, Docker build или duplicate identity.
Постфактум CPU sample не устанавливает отсутствие resource contention в момент
обрыва. Long soak и SLA по этим срезам не заявляются.

Два bounded read-only `REQUEST_LOGS` RPC23:03:25UTC вернули64 строки каждый:
reconnected remote PH028 и local PH011 всё ещё сообщали **1.2.32-dev**.
В PH028 есть watchdog «no ping94s», authenticated session95.132s,
SocketException и reconnect backoff1664ms. Timezone/clock Android log не доказаны;
точная корреляция его локального времени с server UTC не заявляется. PH011
вернул более старый upgrade/reconnect фрагмент; это не новый синхронный сбой.

Независимая сверка **3 октября01:53:03UTC**: catalog19, online14.

| Reported APK | Online устройств |
|---|---|
| 1.2.40-dev | 3 |
| 1.2.34-dev | 2 |
| 1.2.32-dev | 2 |
| 1.2.30-dev | 2 |
| 1.2.22-dev | 5 |

Пять offline устройств не сообщают версию в текущем каталоге. **11 из14 online
остаются на старых APK**; новый код не доказывает обновление парка. F33 должен
сопоставить channel/catalog/artifact/delivery/terminal receipt/new heartbeat.
Watchdog старого APK не объявляется дефектом принятого latest APK.

## Открытые критерии

- Browser visual/keyboard/mobile: `OPEN_URL_POLICY_BLOCKED`, запрет не обходился.
  JSDOM/API/native decoded frames не объявляются браузерными screenshots.
- Kill-switch transport и Android VPN lifecycle не приняты; новая интеграция
  отложена. Unmounted legacy `_tabs` не объявлены новым workflow.
- Durable unknown journal/reconciliation и concurrent provider acceptance OPEN.
- F33 bulk/verified manifest; N01 upload, N03 legacy RPC errors, audit outbox OPEN.
- F34–F36: matrix preview cost, XPath, FPS/quality и реальный input-to-visible latency.
- F39–F41, public rollout, 20–30-device stream+scripts, fault/soak/clone/Android14+
  acceptance OPEN. PR19 остаётся draft/unmerged.
- Previous published head `a9664d8` прошёл все три workflows: backend2330 passed /
  16 skipped. Новые commits имеют собственный CI; его состояние проверяется отдельно.

Raw logs содержат private runtime сведения и остаются вне репозитория.
Evidence JSON публикует allowlisted summaries и SHA256 исходных receipts.
