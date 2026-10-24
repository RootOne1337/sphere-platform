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

## Фактическая приёмка UI439f910

Source439f910 установлен на3015 7октября01:59UTC+5. Full frontend CI:
1690 tests /133 suites, fresh types/build,26pages/73assets,22 archive/installer
methods и18 HTTP probe tests passed. APIeb7a7c26 сохранён. Данные ниже получены
из видимого DOM и оригинальных снимков после установки, не из CSS-теста.

| Viewport | Ширина поля названия | scrollWidth/clientWidth | Проверка/сохранение |
| --- | --- | --- | --- |
| 390×844 | 300px | 390/390 | Перенос на доступные строки |
| 637×884 | 547px вместо68.39 | 637/637 | Оба действия видимы |
| 1280×800 | 457.36px | 1280/1280 | Toolbar помещается |
| 1920×1080 | Визуально проверено | Full desktop view | Обе primary actions доступны |

[390](assets/studio-validation/header-390-after.png) ·
[637](assets/studio-validation/header-637-after.png) ·
[1280](assets/studio-validation/header-1280-after.png) ·
[1920](assets/studio-validation/studio-1920-after.png) ·
[Structured receipt](STUDIO-INSTALLED-ACCEPTANCE.json).

При переходе1920→1280 найден отдельный дефект старого viewport графа:
часть узлов до «Весь граф» оставалась за границей pane. Header принят,
вся responsive страница этим не объявляется завершённой.
[Отдельное исправление resize](STUDIO-CANVAS-RESIZE.md) sourceeb598a5:
1692/133 full local tests и TypeScript passed; установка ещё не подтверждена.

## Установленная приёмка b50d6ae

Следующий UI-only image установлен 7 октября 02:50:47 UTC+5. Title/node fixes
сохранены; resize overview принят на 1920/1280/390, ручной zoom сохраняется,
ELK directions и JSON routes проверены. API eb7a7c26, 45 других контейнеров,
APK и OTA не изменены. Все три CI b50d6ae успешны: frontend 1692/133,
backend 3037 passed / 37 skipped, 55 subtests, coverage 80.36%; Android success.
Старый 439f910 backend rerun attempt 2 отменён следующим push, не объявляется
успешным. Причина его attempt 1 PowerShell timeout не установлена.
[Latest exact runtime/browser/CI receipt](STUDIO-RESIZE-INSTALLED-ACCEPTANCE.json) ·
[Resize acceptance and limits](STUDIO-CANVAS-RESIZE.md).
Эта приёмка не закрывает continuous input, rich recorder, fleet soak или
причину роста диска/RAM и повторных повреждений файлов.
