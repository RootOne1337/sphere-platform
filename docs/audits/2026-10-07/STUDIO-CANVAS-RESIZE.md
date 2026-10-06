# Script Studio: обзор графа после изменения размера окна

Дата: 7 октября 2026, Asia/Yekaterinburg. Связано с EP-014/015 и
[responsive приёмкой](STUDIO-RESPONSIVE-HEADER.md).

## Наблюдение на установленном UI439f910

После проверки схемы на1920×1080 и уменьшения viewport до1280×800 некоторые
узлы оставались вне видимой части холста. Размер pane обновлялся, pan/zoom
сохранялись от прежней геометрии. «Весь граф» вручную возвращал схему в видимую
область. Исправное поле названия и отсутствие horizontal overflow не доказывают
доступность узлов. [Снимок до исправления resize](assets/studio-validation/header-1280-after.png).

Предыдущая подгонка работала только после явного переключения панелей. Изменение
размера браузера, responsive перестройка колонок и высоты toolbar в неё не входили.

## Правило поведения

- В исходном обзоре и после «Весь граф», Fit View, «Упорядочить», изменения
  направления или принятого переключения панелей граф следует за размерами pane.
- ResizeObserver наблюдает только контейнер графа. Первое измерение принадлежит
  React Flow; одинаковые размеры и невидимый контейнер не вызывают fit.
- Серия resize coalesces в одну подгонку после двух animation frames, когда
  React Flow успел обновить свои размеры. Cleanup отменяет кадры и observer;
  старый callback после JSON, снятия доступа или unmount ничего не меняет.
- Ручной pan/zoom, кнопки zoom, drag узла и добавление с фокусом на новом шаге
  сохраняют выбранный оператором ракурс. «Весь граф» возвращает следование.
  Программный onMoveStart с event=null не считается ручным перемещением.
- Overview допускает zoom0.15–1, совпадающий с нижней границей React Flow.
  Прежний минимум0.65 не позволял вместить более широкую схему в узкий pane.
  При экстремально большом графе ограничение0.15 остаётся: zoom/pan доступны,
  гарантии читаемости500 узлов одновременно на телефоне нет.

Изменяется только viewport. DAG, переходы, параметры, positions, история и
исполняемый hash не переписываются; REST-запросов ради resize нет.

[Hook](../../../frontend/src/features/scripts/studio/useCanvasOverview.ts) ·
[Страница](../../../frontend/app/%28dashboard%29/scripts/builder/page.tsx) ·
[Integration tests](../../../frontend/__tests__/scripts/builder-load.test.tsx).
Ссылка на страницу содержит URL-encoded скобки; физический путь —
`frontend/app/(dashboard)/scripts/builder/page.tsx`.

Первичные API contracts: [React Flow onMoveStart](https://reactflow.dev/api-reference/react-flow#onmovestart),
[OnMove event/null](https://reactflow.dev/api-reference/types/on-move),
[Controls callbacks](https://reactflow.dev/api-reference/components/controls).
Локальный установленный package source дополнительно подтверждает порядок
default Controls fitView и onFitView; handler включает следование без второго fit.

## Проверки кандидата

Полный frontend suite:1692 tests /133 suites passed;59 scoped tests /2 suites
passed, source-only TypeScript passed. Новые integration cases:
реальный mount страницы, resize burst, subpixel duplicate, программный move,
ручное перемещение между двумя кадрами, возврат overview, скрытый pane,
JSON/unmount и stale callback. Node coordinates и routes неизменны,
API publication не выполняется. Standard fresh types/build/image остаются CI gate.

Предварительный source-кандидат eb598a5 включён в установленный b50d6ae;
последующая CI/runtime/browser приёмка описана ниже. EP-014 целиком и
ledger 9/41 этим не закрываются.

## Установленная приёмка b50d6ae

7 октября 02:50:47 UTC+5 на 3015 установлен exact CI image b50d6ae.
Все три workflows прошли; frontend 1692/133, backend 3037/37 и Android success.
[Полный receipt с digest, run/attempt и DOM measurements](STUDIO-RESIZE-INSTALLED-ACCEPTANCE.json).
Установщик проверял только image/runtime; его browserVerified=false сохранён.
Последующая браузерная приёмка записана отдельно, без изменения старого флага.

| Действие без дополнительного Fit View | Результат |
| --- | --- |
| Overview 1920×1080 → 1280×800 | Все три узла внутри pane; zoom 0.684575 |
| Native Zoom In, затем 1280 → 1920 | Transform сохранён точно: translate(125.991px,16.2421px), scale(0.82149) |
| «Весь граф», ELK RIGHT, resize 1920 → 1280 | Все узлы внутри pane; zoom 0.440928 |
| ELK DOWN, resize до 390×844 | Все узлы внутри pane; title 300 px; horizontal overflow нет |
| JSON → граф → серверная проверка | 3 шага / 2 связи, оба on_success сохранены; hash 18d4f96c4c0d… |

На телефоне pane идёт ниже toolbar/библиотеки; для снимка библиотека скрыта
явной штатной кнопкой и страница прокручена. Это не заявление, что весь Studio
или 500 узлов помещаются в один мобильный viewport. Temporary override сброшен.
Наблюдаемых console warning/error нет. Сценарий не публиковался и не запускался.
API подтвердил структуру/Lua safety, а не новый action contract/Android semantics.

[Desktop 1920](assets/studio-validation/resize-desktop-1920.jpg) ·
[Resize 1280](assets/studio-validation/resize-overview-1280.jpg) ·
[Mobile 390](assets/studio-validation/resize-mobile-390.jpg).
