# Studio: установленная компоновка и запись кнопок Android

9 октября 2026, Asia/Yekaterinburg. Конечное наблюдение 8 октября,
21:43–21:51 UTC. UI source **ec3f22678f20c16c221d4e2d02810d4f8122e6af**
установлен на **3015**; revision прочитан из настоящего браузера.

## Что изменилось

Compact Studio показывает одну рабочую область и постоянные переключатели
«Схема», «Действия», «Параметры», «Устройство». Библиотека больше не исчезает
при открытии лаборатории. В широком окне библиотека, схема и лаборатория
доступны одновременно. Шапка, проверка и сохранение остаются вне скролла
рабочей области; второстепенные инструменты доступны через «Ещё».

Переключение панели сохраняет очередь и выбранное устройство, прекращая
запись и скрытый ввод. Возврат не включает запись автоматически и требует
нового видеокадра. Late ACK обновляет исходный pending slot; неизвестный
исход не становится успехом и не повторяется автоматически.

Общая кнопка возврата поддерживает известную внутреннюю историю вкладки.
Каждый history entry хранит собственную ограниченную геометрию прокрутки;
API-ответы, токены, исходник сценария и изображения там не сохраняются.

## Установка и её границы

Reviewed artifact из frontend CI **37847915500**: 120872803 bytes,
26 HTTP pages и 73 client assets. Ожидаемый image ID прочитан из
аутентифицированного CI log, затем проверен installer admission:
`sha256:3831170254b51f12af7538bc1dd4dac5315666f83481aac0568c2609b1cc6ff6`.

Docker загрузил проверенный совместимый descriptor:
`sha256:2cb783f7ab485dcf39c4b6ce7d573b943edfeb0f09ecc3c08867bbcf2b49cbfe`.
UI container started **2026-10-08T21:43:08.839378017Z**.
Installer подтвердил сохранность **45 других контейнеров**, API be803773,
schema и OTA catalog. PH011 продолжает работать с **1.2.49-dev / 10249**.
APK и нормальный OTA channel этим checkpoint не обновлялись.
Resource admission findings — пустой список. Широкая очистка Docker,
compaction, новый storage collector или перезагрузка ПК не выполнялись.

[Scalar receipt и checksums](STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.json)
содержат source, CI, installation identity и конечные browser observations.
Private installer baseline/config/logs остаются в `.local-pilot`.

## Проверки исходников

Все четыре hosted workflows **для exact installed source ec3f2267** завершены
успешно: frontend37847915500, backend37847915547, Android37847915783,
preview37847915566. Frontend **1936 passed / 139 suites**; backend
**3346 passed / 37 skipped / 229 subtests passed**,2warnings, coverage80.72%.
Types/build, canonical action contract, image admission, RLS, Ruff/mypy,
security checks, production bootstrap и Alembic passed. Android variant tests
и signed smoke builds successful; это не установка новой APK на парк.

Локальный полный frontend1936/139suites; navigation10 и Builder54focused
regressions, nonincremental TypeScript passed. Коммиты после source checkpoint,
содержащие только документацию/evidence, не объявляются этой exact-source CI.

## Реальная визуальная проверка

| Viewport | Конечное наблюдение |
| --- | --- |
| 844×390 | Main 844×342, без горизонтального/внешнего вертикального overflow; graph 844×195 |
| 390×844 | Четыре панели и шапка доступны; библиотека 32 действий; badge больше не накрывает меню |
| 1440×900 | Library 220px, graph 434.09px, laboratory 520.91px; все три доступны одновременно |

На промежуточном b36adbb3 graph имел около112px по высоте. После переноса
compact переключателей в toolbar и уменьшения низкой шапки он получил195px.
Это измерение actual DOM viewport, не только настройка browser capability.

- [Промежуточный landscape](assets/responsive-workspace/landscape-before.jpg).
- [Конечный landscape](assets/responsive-workspace/landscape-final.jpg).
- [Портретная библиотека](assets/responsive-workspace/portrait-actions-final.jpg).

«Ещё» открыл настоящие импорт, экспорт, направление, упорядочивание и запуск.
В compact библиотеке добавлен отдельный sleep node: graph стал4 nodes/2 edges,
существующие связи не изменились. Панель параметров показала ms1000,
переходы/retry/timeout. Undo вернул3 nodes/2 edges и чистую опубликованную v1.
Ни сохранение, ни запуск версии в этой проверке не выполнялись.

В 195px landscape обзор вертикальной цепочки остаётся мелким: три узла
измерены примерно38×20px. Доступны zoom и направление схемы; улучшение
адаптивного overview остаётся UX follow-up. Не считать этот checkpoint
полной приёмкой всех физических телефонов, IME/keyboard и touch gestures.

## Recorder: четыре кнопки проверены на установленном UI

PH011 выбран через реальный каталог. После свежего кадра normal Control
подтвердил native readiness. Start ожидал known release; затем четыре
кнопки нажаты последовательно, с наблюдением APK outcome перед следующей:

| Порядок | Кнопка | Android key code | Наблюдение |
| --- | --- | --- | --- |
| 1 | Домой | 3 | Подтверждено APK |
| 2 | Недавние | 187 | Подтверждено APK |
| 3 | Назад | 4 | Подтверждено APK |
| 4 | Меню | 82 | Подтверждено APK |

После смены1440×900→390×844 и Actions→Device сохранены ровно четыре строки
в исходном порядке. Recording OFF: доступна «Записать действия». Возврат
не повторил Android commands. View выбран явно. Compact queue показала все
четыре строки в одной основной прокрутке, без дополнительного224px скролла.
[Конечная запись](assets/responsive-workspace/recorded-navigation.jpg)
не содержит Android pixels. В21:47:23UTC DOM подтвердил4/4 outcomes.

После доказательства явно очищена только созданная тестовая очередь.
Исходная published v1 не изменена; сценарий не запущен. APK confirmation
не доказывает визуальный результат конкретного приложения. В частности,
Android Menu может ничего не открыть, хотя key event выполнен.

Component regressions отдельно проверяют click→submitted→pending export
block→Stop→late APK confirmed→один key_event при DAG export для всех4кнопок.
Это evidence export fixtures; живой canary не вставлял запись в published graph.

## Точный возврат в каталог

Из каталога при main scrollTop **2132.5px** coordinate click открыл видимую
карточку `08615c8f-599a-4aa0-9b81-06efe721be38`. Browser Back после route
commit вернул **2132.5px**. Отдельный повтор с общей кнопкой «Вернуться на
предыдущую страницу» также вернул **2132.5px** после завершения перехода.
[Каталог после browser Back](assets/responsive-workspace/catalog-back-final.jpg).

Проверен конечный результат после route commit, не мгновенное промежуточное
scrollTop во время загрузки. Preview884→884 — историческое отдельное наблюдение.
Controller tests10 покрывают clamp перед history write, delayed data,
внутренние области, лимиты, cleanup и смену identity.

## Что остаётся открытым

- **Recorder сохраняет completed click/swipe endpoints.** Normal Control
  использует live native DOWN/MOVE/UP, но recording mode не сохраняет MOVE path.
- XPath добавляется явно из inspector как planned future action. Обычное
  нажатие не получает автоматически atomic tree/PNG/crop/pixel bundle.
- Native screenshot и stream frame — разные источники. Нет frame-exact
  playback и доказанной синхронизации дерева, нажатия и изображения.
- Browser Back/Forward dirty Studio ещё не имеют полноценного leave dialog;
  общая кнопка проходит существующий guard. F5 не сохраняет tab-local geometry.
- Live same-session token refresh, idle `native_receipt_timeout`, distributed
  controller/task lease, durable admission reconciliation и storage writer
  attribution не закрыты.

Product ledger **9 accepted / 41 open**. Эти частные проверки не закрывают
SF26-05/06 целиком и не заменяют отдельные8release gates.
[Rich recorder contract](../2026-10-08/STUDIO-RECORDER-NEXT-P1.md) ·
[Idle P1](../2026-10-08/STUDIO-IDLE-RECEIPT-FOLLOWUP.md) ·
[Storage window](../2026-10-08/STORAGE-WINDOW-COMPLETION.md) ·
[Canonical state](../../operations/CURRENT-STATE.md).

В конце viewport override снят, временные preview tabs закрыты и dev server
остановлен. Пользовательская вкладка исходного сценария оставлена открытой.
