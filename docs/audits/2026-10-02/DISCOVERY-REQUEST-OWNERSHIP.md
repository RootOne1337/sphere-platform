# Обнаружение: контракт запроса и принадлежность результата

**Дата:** 2 октября 2026, Asia/Yekaterinburg.<br />
**Implementation / установленный review UI:** `d4364e5e640929eef9a9daebdb97ed81783d605c`.<br />
**Backend:** `5fcf18a`; API-контракт не изменён.

[F19](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f19) · [F20](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f20) · [Журнал](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Evidence](DISCOVERY-REQUEST-OWNERSHIP-EVIDENCE.json) · [Текущее состояние](../../operations/CURRENT-STATE.md)

## Доказанные дефекты

Замороженный аудит описывает два противоречия: текст обещал отсутствие изменений при включённой регистрации; заголовок завершённого scan использовал редактируемый CIDR следующего запроса. Они подтверждены before/after component tests с настоящим React Query и mock HTTP transport.

Дополнительный **N02**, найденный при сверке с зарегистрированным backend: прежний UI отправлял `ports` без обязательного `workstation_id`. `DiscoverRequest` требует UUID и `port_range: [low, high]`; прежний payload отвергнут HTTP422 авторизованным запросом к установленному API через review gateway. Ошибка возникает до запуска scan. Отдельная проверка того же installed Pydantic schema принимает исправленный payload; она не запускает DB/PC Agent/Android команды.

Прежний response UI ожидал `registered: boolean` в строке устройства. Backend выдаёт `already_registered` и nullable `registered_id`. Поэтому существующее или только что добавленное устройство могло выглядеть незарегистрированным. `scanned` вычисляется service как размер подсети × диапазон портов; UI теперь называет это **объёмом запроса**, без утверждения, что все проверки действительно выполнены.

Source anchors: [страница](../../../frontend/app/%28dashboard%29/discovery/page.tsx), [schema](../../../backend/schemas/discovery.py), [router](../../../backend/api/v1/discovery/router.py), [service](../../../backend/services/discovery_service.py), [regressions](../../../frontend/__tests__/discovery/request-context.test.tsx).

## Исправленное поведение

- Основной путь явно указан: Android APK подключается сам; ADB/PC Agent не являются обязательной частью развёртывания. Есть ссылка на настоящий парк устройств. PC Agent не устанавливался этим batch.
- Дополнительный legacy ADB-поиск требует ID уже существующего PC Agent; без UUID кнопка недоступна. Это UUID input, не готовый host picker: API каталога workstations в текущем приложении отсутствует.
- Порты — две включительные границы в 1–65535, lower ≤ upper; дробь, суффикс и выход за границу не отбрасываются молча. Timeout100–5000мс. CIDR проходит штатную backend validation.
- Регистрация по умолчанию выключена. Текст и результат различают scan-only и добавление новых записей; UI передаёт выбранное значение `auto_register`.
- Mutation получает копию request scope. Результат хранит этот request и client receive time; правка формы во время запроса или после его окончания не меняет CIDR/ports/host/mode уже полученного ответа.
- Response envelope проверяется до таблицы/empty state. Ошибка или несовместимый ответ не изображаются успешным отсутствием устройств.
- `retry:false` исключает наследование глобального mutation retry. «Повторить исходный поиск» повторяет сохранённые параметры, с явным предупреждением о возможной регистрации. Запрос после правки формы запускается отдельно через «Начать поиск».
- Строки различают «Уже было в Sphere», «Добавлено в Sphere» и «Не зарегистрировано» по действительным backend fields.

## Проверки

| Проверка | Результат |
| --- | --- |
| 11 нынешних tests на before page `d5d3d14` | 10 failed / 1 rendering control passed / 0 runtime errors |
| Та же component suite после исправления | 11 passed |
| Полный frontend | 92 suites / 729 passed / 0 failed / 0 skipped |
| Types | `tsc --noEmit` exit0 |
| Реальная installed schema | старый payload rejected/missing workstation; новый typed range accepted |
| Авторизованный старый payload через API3015 | HTTP422, missing `workstation_id`, scan не запускался |
| Docker production build | passed, Next15.5.26 / Node24, compiled stamp `d4364e5` |
| Установка 05:08:58 / restart проверен 05:13:08 UTC+5 | login/API/static asset/Prometheus/Grafana/events WS passed; 19 records, reported online14/offline5 |

Before harness сначала имел module resolution/duplicate React проблему; эти ошибки не считаются подтверждением дефекта страницы. Только повтор с общим dependency tree, десятью assertion failures и проходящим контрольным тестом используется как before proof. Полный набор729 выполнен перед последним уточнением подписи `scanned`; после этой текстовой правки все11 специализированных tests повторены и прошли.

## Ограничения и новый follow-up

**N03 OPEN:** `DiscoveryService._discover_devices_via_agent` возвращает пустой список при отсутствии PubSubRouter, timeout и RPC exception. Поэтому HTTP200/empty scan этого legacy service не позволяет отличить недоступность PC Agent от успешного отсутствия устройств. Это source finding, а не наблюдение живого scan. Backend error semantics/tenant-safe host selection требуют отдельного исправления; F19/F20 закрыты только по своим source-критериям, а весь legacy workflow не объявляется принятой enterprise-функцией.

Живое сканирование сети, PC Agent installation, массовая регистрация и создание Android устройств не выполнялись. Fresh browser walkthrough по-прежнему **OPEN_URL_POLICY_BLOCKED**. Tests не доказывают внешний вид или реальную сетевую доступность. Public frontend/OTA/APK/tunnels не обновлялись; review3015 обновлён отдельно и rollback image0f4530c сохранён. После restart обоих review контейнеров повторены login/API/observability/events WS проверки; все14 прежних контейнеров сохранили IDs/images/StartedAt. PR19 остаётся draft.

Совокупно **26/41 исходных source findings исправлены**, **15 исходных OPEN**, дополнительные N01(Android artifacts) и N03(legacy discovery error semantics) OPEN. [Remote PH025 rerun](REVIEW-RUNTIME-AND-REMOTE-RERUN.md) остаётся самостоятельным finite proof; discovery tests к нему не прибавляют новые Android executions.
