# Script Studio: вставленный шаг скрывал существующий узел

Дата: 7 октября 2026, Asia/Yekaterinburg. Baseline installed99af20d / APIeb7a7c26.
Связано с SF26-12 / EP-014,015; общий ledger9/41 не закрывается этим дефектом.

## Доказательство в реальном браузере

Start→End, режим «Вставить в цепочку», добавить sleep. Wire DAG корректен:
Start→sleep→End,3nodes/2edges. Но старое положение End сохранялось, тогда как
новый sleep получал arranged position, совпадающую с прежним End. На1920×1080
после «Весь граф» bounding boxes обоих узлов были буквально одинаковыми:
left901/top666/width256/height133. End визуально скрыт под sleep.
[Оригинальный снимок до исправления](assets/studio-validation/chain-overlap-before.png).
При переносе записи Home/пауза/XPath проявилась та же причина.

## Изменение

При синхронизации source→canvas сначала резервируются все сохранённые позиции
узлов, остающихся в документе. Новые узлы получают свободное место с учётом
измеренных размеров и уже размещённых новых узлов; существующие ручные позиции
не сдвигаются. Удалённые узлы не занимают место. Явный drag/drop по-прежнему
сохраняет выбранную оператором точку, в том числе намеренное наложение.
Это placement UI-only: transitions, порядок записи и executable hash не меняются.
Кнопка «Упорядочить» остаётся явным способом изменить всю раскладку.

Проверены регрессии: новый шаг до существующего End в массиве; увеличенные
measured bounds; несколько записанных шагов; отсутствие mutation; сохранение
ручных координат, deliberate drop и параметров; удалённые obstacles. React
integration test проверяет реальное добавление через страницу и Start→new→End
в JSON, без API write.57 targeted tests /2 suites passed; предшествующий398/17
Studio suite и source-only types passed. Финальный full CI и browser после
установки относятся к отдельному новому SHA, не к baseline.

## Повторная функциональная проверка записи baseline

PH010 / APK1.2.45-dev: Home → pending → confirmed APK,482ms command ACK.
XPath MeshCentral Agent выбран без клика Android,45nodes; selector добавлен
после Home, пометка «В план · не выполнялся». Перенос в граф сохранил порядок
Home→sleep60000→tap_element. Пауза ограничена60s настройкой записи. Script/task
не публиковались и не запускались. ACK не означает input-to-frame latency;
XPath дерево и кадр не объявляются атомарным correlated evidence.
