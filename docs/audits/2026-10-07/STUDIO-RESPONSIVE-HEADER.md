# Script Studio: responsive header и проверка установленного графа

Дата: 7 октября 2026, Asia/Yekaterinburg. Installed baseline: UI99af20d / APIeb7a7c26,
`http://127.0.0.1:3015/scripts/builder`. Новый source описан отдельно от baseline.

## Доказанный дефект

При viewport637×884 блок названия конкурировал с проверкой/сохранением в одной
flex-строке. `#studio-name` имел ширину68.39px: «Новый сценарий» визуально обрезался,
служебная строка Script Studio/DAG переносилась внутри слишком узкого блока.
Общего horizontal overflow при этом не было; проверка scrollWidth недостаточна.
Оригинальный [снимок браузера до изменения](assets/studio-validation/header-narrow-before.png).

Ниже1280px название и действия теперь занимают самостоятельные строки;
кнопка возврата не сжимается, служебная строка допускает перенос. На широком
экране сохраняется единый toolbar. Название, права, dirty guard, check/save и
wire DAG не меняются. CSS-классы отдельными unit tests не закрепляются:
критерий — читаемое поле и доступные действия в фактическом браузере.

## Подтверждённые действия baseline

В authenticated установленном UI добавлен отдельный sleep:3nodes/1edge,
start→end сохранён, показывается ошибка незавершённого черновика. Существующая
линия выбрана, цель изменена на sleep; delete-only action даёт3nodes/0edges;
Undo возвращает3nodes/1edge. Локальный тестовый граф не опубликован и не запущен.
Выбор короткой SVG-линии автоматическим locator.click попадал в прозрачный
reconnect handle; реальный клик в центр линии открыл редактор. Это ограничение
автоматизации не записано как подтверждённая неисправность браузерного UI.

## Проверки кандидата

395 tests /17 suites Script Studio passed; отдельный source-only TypeScript
passed. Стандартный local type-check остановился на stale generated
`.next/types/validator.ts`, ссылающемся на удалённый root page; его результат
не считается положительным. Чистые generated types/build/image должны пройти
hosted CI нового SHA. Существующий full CIc6339b2 не подменяет проверку кандидата.

Responsive matrix после установки:390×844,637×884,1280×800,1920×1080.
Проверить поле названия, обе primary actions, toolbar, отсутствие горизонтального
переполнения, graph zoom и мобильный доступ к canvas/inspector. Снимки нового
source и результаты добавляются после фактической установки, не заранее.

Continuous DOWN/MOVE/UP, нативный crop/pixel evidence, correlated playback,
APK capabilities и массовые действия не входят в приёмку этого исправления.
Текущий ledger9/41 сохранён. [Зависимости и следующая работа](../2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md).
