# Viewer input: отказ без потери видеосессии

Дата: **7 октября 2026**, Asia/Yekaterinburg. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Область: existing discrete WS protocol; не continuous injector.
Статус исходного source среза: regression passed, тогда UI b50d6ae/API114775a.
**Позднейшая доставка:** UI/API a41c4e6 установлены7октября; exact source CI и
реальный transport/browser canary записаны [отдельно](VIEWER-INPUT-DELIVERY.md).
Frozen source receipt ниже не переписывается как installed evidence.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Studio](../../operations/SCRIPT-STUDIO.md) ·
[Continuous requirements](../2026-10-06/CONTINUOUS-INPUT-INTEGRATION.md) ·
[Recorder follow-up](../2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md).

## Доказанный дефект

Исходный [WS handler](../../../backend/api/ws/stream/router.py) использовал
`int(data.get("x", 0))`, такой же default/coercion остальных координат и
`str(data.get("text", ""))`. Примеры, подтверждённые выражениями Python:

| Вход | Старое поведение | Исправление |
| --- | --- | --- |
| click без x/y | Передача 0/0 | Отказ до dispatch |
| boolean/string/float вместо integer | Преобразование/усечение | Строгий JSON integer |
| Нечисловая строка | ValueError во внешнем catch, viewer удаляется | Фиксированный отказ, видео сохраняется |
| list/null вместо объекта | Исключение `.get` | Отказ формы пакета |
| text с object/number | Python string representation | Только исходная строка |
| Слишком длинный swipe | Неограниченная длительность | 0–60 000 ms |

Это source/protocol defect, **не доказательство**, что обычные клики пользователя
терялись именно по этой причине. FPS/input-to-frame latency этим не измерены.

## Контракт

[Pure admission](../../../backend/websocket/viewer_input.py) не имеет SQL/Redis,
инжекции, shell, логирования или внешних зависимостей. Возвращает новый словарь
с поддержанными полями, не меняет исходный объект.

1. Coordinates/keycode — integer token без boolean/float/string, 0–2 147 483 647.
   Это предел Android Int, **не проверка physical display bounds**; существующая
   APK capture geometry остаётся отдельной проверкой.
2. Все четыре swipe coordinates обязательны. Default300ms сохраняется только
   при отсутствии duration_ms; явный null/неверный тип отвергается.
3. Text — до65 536 code points /262 144 UTF-8 bytes; lone surrogate отвергается.
   UTF-8 admission не обещает Unicode/IME capability установленного APK.
4. Browser session/tenant metadata не пересылаются. Router добавляет свою session
   после fresh RBAC/tenant check. Это **не owner lease/geometry epoch fencing**.
5. request_keyframe — video control, pong не вызывает Android. Unknown types,
   включая touch_down, отвергаются и не объявляются поддержанными.
6. Ошибка `stream_input_invalid` содержит только фиксированный reason:
   invalid_message, invalid_parameter, unsupported_message. Private input,
   поля пользователя и raw exception не включаются в ответ.
7. JSON/UTF-8 decode failure, digit/nesting limit не прекращают viewer. Неверная форма первого auth
   сообщения закрывается4001 до SQL/регистрации. Внешний log хранит error type,
   а не `str(exc)`. Нет автоматического replay или fake execution ACK.

Flat WS keyevent/text сохраняют прежний transport contract. Рабочие клавиши и
текст веба используют acknowledged HTTP shell path; их не переводили на
неподдержанный installed APK path. Root/auth scope/permissions не расширены.

## Веб

[DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx) отделяет
отказ команды от stream failure. Dismissible сообщение над изображением не
блокирует canvas, не скрывает кадр и не меняет decoder state. Held local gesture
отменяется; новое явное действие сохраняет role/socket/frame ownership checks.
Reconnect/device/auth change очищает уведомление. Transport/permission failures
по-прежнему блокируют управление. UI показывает только фиксированные строки,
не private server payload. Ordered recorder всё ещё различает WS submission и
HTTP APK ACK; correlated outcome malformed WS request здесь не добавлен.

## Проверки

**66 tests /44 subtests passed**,65,48s: source mounted read-only в отдельный
контейнер с зависимостями exact accepted image114775a. Fresh PostgreSQL15/Redis7.2
работали в отдельном internal network/namespace; loopback endpoints, host ports
отсутствовали. Migrations применялись **только к одноразовой tmpfs базе**,
не к live pilot. Три owned containers/network удалены по immutable ID/unique label.

Проверены cross-worker/tenant/RBAC/revocation/backpressure/capture start,
malformed shapes/types/missing coordinates, следующий H.264 frame после отказа
и отдельный корректный click. Spoofed session отброшена. Pure tests проверяют
Int/duration/Unicode/no coercion/source mutation; ASGI — bad JSON/UTF-8/cleanup.

**58 frontend tests /3 suites passed**: pointer/reconnect/navigation,
cancel held gesture без отключения canvas, subsequent explicit click, dismiss
и отсутствие private payload. Source TypeScript, scoped Ruff и **mypy двух
production files в чистом dependency image passed**.

Обычный local tsc не принят: старый `.next/types/validator.ts` ссылается на
удалённый root page. Source check не включает generated types; fresh hosted
types/build обязательны. Первая mypy попытка превысила16/24MiB tmpfs cache:
traceback `sqlite3.OperationalError: database or disk is full` относится к
**ограниченному cache контейнера**, не C: или приложению. Повтор с disabled
persisted cache прошёл; host disk/RAM leak этим не закрыт.

**52 delivery unittest methods passed**: новый source-boundary case допускает
ровно два reviewed input files; RBAC/connection manager по-прежнему отвергаются.
[Структурированный source receipt](VIEWER-INPUT-SOURCE-EVIDENCE.json).

## Предыдущий CI и позднейший Home canary

Exact **d112337b12f9f470d527e1ebb2cc8a5c9b114970**, все workflows success:

- [Backend37542117846](https://github.com/RootOne1337/sphere-platform/actions/runs/37542117846):
  3066 passed/37 skipped/147 subtests,coverage80,39%; все6jobs success.
- [Frontend37542117769](https://github.com/RootOne1337/sphere-platform/actions/runs/37542117769):
  success, включая fresh types/build.
- [Android37542117872](https://github.com/RootOne1337/sphere-platform/actions/runs/37542117872):
  tests/lint/signed release smoke success.
- [Preview37542117745](https://github.com/RootOne1337/sphere-platform/actions/runs/37542117745):
  success guard; не production deploy.

Это **не CI новой правки**. Installed API114775a сохранён; d112337 содержит
delivery tools/docs и не переустанавливался. Отдельный live PH010 Home на уже
открытом launcher подтверждён APK за **464ms**, sample count1; stream закрыт.
Это не p95/moving FPS/input-to-rendered-frame latency. APK1.2.45-dev сохранён.
Первоначальный no-input contract receipt не переписан; Home — позднейший canary.

## Доставка и открытые gates

Installer допускает ровно два дополнительных packaged paths: WS router и
pure viewer_input.py. RBAC/connection manager/dependency/migration/bootstrap
changes сохраняют отказ. На исходном срезе требовались full exact-source CI,
bounded artifact/config identity, backend-only plan, SQL/OTA/45container preservation
и authenticated invalid-input canary. Они приняты позднее в
[installed delivery](VIEWER-INPUT-DELIVERY.md). Source overlay не устанавливался.
Browser malformed-notice canary остаётся открыт; notice React-tested.
[Backend delivery](REVIEWED-BACKEND-DELIVERY.md).

Continuous DOWN/MOVE/UP остаётся P1: root injector, single-owner lease,
geometry epochs, bounded MOVE coalescing и local terminal cleanup. Rich recorder,
native crop/pixel manifest, task artifacts, correlated replay и fleet soak
открыты отдельно; ledger **9/41** не изменён. Причины storage/RAM growth и
filesystem corruption не объявлены решёнными.
