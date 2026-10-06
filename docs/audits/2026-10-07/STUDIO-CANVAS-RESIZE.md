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

Это source-кандидат после фактической приёмки UI439f910. Hosted сборка и повторная
browser проверка изменения окна должны быть записаны отдельно до заявления,
что resize исправлен на3015. EP-014 целиком и ledger9/41 этим не закрываются.
