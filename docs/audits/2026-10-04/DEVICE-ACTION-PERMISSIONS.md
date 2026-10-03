# F39 — действия реестра устройств и отзыв прав в диалогах

Дата: 4 октября 2026, UTC+5. Продолжение [F39](../2026-10-03/SESSION-CAPABILITIES.md)
и [N10](VIEWER-AUTHORIZATION.md). **F39 PARTIAL**: этот этап покрывает реестр
устройств; остальные административные формы и browser acceptance ещё открыты.

## Подтверждённый дефект

На исходниках `1bccb47` backend уже отклонял операции без нужного permission,
но `/devices` показывал активные mutation buttons и меню пользователю viewer.
Диалог удаления и Enter в переименовании не учитывали полученный отзыв прав.
Это несоответствие интерфейса серверному контракту; обхода HTTP authorization
данным этапом не доказано, новые серверные права не выдаются.

На прежних исходниках в Node24 выполнены 10 новых workflow cases:
**9 assertion failures / 1 passed / 0 runtime-error suites**. Ошибки окружения
или отсутствие нового компонента в промежуточном mock не считаются defect proof.
Повтор before выполнен на отдельном git archive исходного приложения.

## Контракт действий

| Действие интерфейса | HTTP operation | Permission существующего backend |
|---|---|---|
| Переименование / сервер | PUT `/devices/:id` | `device:write` |
| Массовый перезапуск | POST `/devices/bulk/action` | `device:write` |
| Назначение группы | POST `/groups/:id/devices/move` | `device:write` |
| Назначение локации | POST `/locations/:id/devices` | `device:write` |
| Удаление одного устройства | DELETE `/devices/:id` | `device:delete` |
| Массовое удаление | DELETE `/devices/bulk` | `device:delete` |
| Массовый отзыв VPN | POST `/vpn/revoke/bulk` | `vpn:mass_operation` |

Разрешения берутся из проверенного `/auth/capabilities`, без локальной иерархии
ролей. `device:bulk_action` не подставляется вместо фактического guard `device:write`.
Роль device_manager может изменять устройство, но не получает право удаления
или массового отзыва VPN. Viewer/script_runner сохраняют чтение реестра.

## Изменения

- Toolbar и каждое действие меню используют отдельное разрешение.
- Переход к диалогу и обработчик отправки повторно проверяют текущий permission.
- Delete confirmation имеет обязательное `canConfirm`; bulk component — `canDelete`.
  Отсутствующий/отрицательный grant не оставляет кнопку активной.
- Меню без explicit permission decision не предлагает мутации. При смене decision
  прежняя ячейка/popup выводится из обращения; повторное открытие использует новые права.
- Отзыв уже полученного разрешения блокирует подтверждение удаления/VPN и Enter
  переименования. Отмена остаётся доступной, если операция ещё не отправлена.
- В том же session scope сохранены локальные draft/selection. Смена identity/role
  может вывести private subtree из обращения согласно существующему session fence;
  старые черновики не обещаются для другой identity.
- Pending/failed capability ответ объясняется в UI. Свежий verified grant возвращает
  действие; неудачный refresh не использует старое административное разрешение.
- Уже отправленный HTTP запрос не отменяется задним числом. Backend заново проверяет
  текущую DB role; клиентская проверка не заменяет authorization и не обещает мгновенное
  знание роли между polls.

## Проверки

1. Новые JSDOM workflow cases: viewer/script_runner, раздельные manager permissions,
   pending/failed grants, отзыв single/bulk delete, rename Enter/draft и VPN revoke,
   сохранение разрешённого удаления с точным выбранным target.
2. Настоящие Radix menus: независимое delete permission, смена открытого меню,
   отсутствие explicit decision. Проверяется DOM/input semantics, не визуальная верстка.
3. Реальный CapabilitiesProvider: pending → denied → refresh failure и verified grant.
4. Реальный HTTP/SQL/Redis: старый admin JWT после DB downgrade отклоняется на восьми
   действиях реестра; manager update допускается, delete/VPN отсутствуют в capabilities.
   Для group/location denial используется valid UUID без domain lookup: это проверка
   permission precedence, а не приёмка назначения в существующую группу/локацию.
5. Полный frontend tests/types/build и immutable-image checks учитываются отдельно
   от исходного прогона. Результат установки описан в отдельном разделе ниже.

Рабочие Android permissions, APK, API/Tuna/OTA не меняются для этого UI исправления.
Живое удаление, reboot и VPN команды в качестве теста не отправляются.

Source gate: **106 suites / 997 frontend tests passed**, Node24 types passed;
**73 actual PostgreSQL/Redis tests passed**, изменённый Python test прошёл Ruff.
15 frontend cases и 20 HTTP cases добавлены поверх предыдущего этапа; исходный
before проверяет 10 workflow cases. Intermediate mock/async/fixture ошибки не
выдаются за отказы продукта. Image build/install и fresh browser остаются отдельными gates.

## Следующие пункты F39

| Раздел | Незавершённая работа |
|---|---|
| Группы / локации | Проверить все create/edit/member/delete forms по server permissions |
| Скрипты / задачи | Execute отдельно от write/read; отзыв права на открытом Run/rollback/archive |
| Оркестрация / расписания | Write отдельно от execute и schedule:write; submission guards |
| Аккаунты / события / сессии | Mutation affordances и открытые формы при отзыве права |
| Пользователи / настройки / OTA / VPN | Сверить role-specific guards, публикацию, recovery и bulk operations |
| Все страницы | Browser keyboard/mobile/layout и реальный операторский walkthrough |

[История исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Текущая установка](../../operations/CURRENT-STATE.md) ·
[F34: следующий transport этап](MATRIX-PREVIEW-PLAN.md).


## Собранный веб и установленный runtime

UI **81d065a** установлен **4 октября 2026, 01:19 UTC+5**, проверка завершена **4 октября 2026, 01:20 UTC+5**.
В образе повторены 106 наборов / 997 тестов; подключались только архивные тесты,
исходники приложения не подменялись. API остаётся **37bb436**; 73 связанных проверки
прошли в его неизменённом образе с PostgreSQL и Redis.
Семь срезов сохранили 14 online APK 10244, heartbeat <60 с и даты соединений до установки.
15 соседних контейнеров, API/Tuna и SHA каталога OTA сохранены. Подтверждены login HTTP 200,
capabilities 200/no-store с ожидаемыми identity/permissions, anonymous 401 и Prometheus up=1.
Source CI **81d065a**: Frontend, Preview, Android и Backend — success. Первое наблюдение и завершение CI записаны отдельно в evidence.

Это проверка API, JSDOM и образов. Визуальная приёмка остаётся OPEN_URL_POLICY_BLOCKED;
отрисовка, мобильная верстка, клавиатурная навигация и остальные страницы не приняты.
Конечное число срезов не доказывает непрерывный uptime или отсутствие кратких событий
между запросами. Предыдущее неудачное окно N10 не переписывается этим новым результатом.
[Публичное evidence](DEVICE-ACTION-PERMISSIONS-EVIDENCE.json).


Сверены 11 изменённых документов, 801 относительная ссылка/якорь и два JSON;
`git diff --check` прошёл. Исходный frozen audit сохранён. OpenAPI остаётся
176 операций / 138 путей; это проверка каталога, не приёмка всех операций.
