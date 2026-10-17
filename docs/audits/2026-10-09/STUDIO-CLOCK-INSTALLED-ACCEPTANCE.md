# Studio: clock correction установлен и проверен на PH011

Дата: 9 октября 2026, Asia/Yekaterinburg. Установка 02:28 UTC / 07:28 UTC+5.
Проверка браузера 02:29–02:34 UTC. UI `60be6ecd0b13e33715761b53b781ad190c1e3e6e`, API `be803773`.
Машинные значения и границы: [receipt](STUDIO-CLOCK-INSTALLED-ACCEPTANCE.json).

## Результат

Исправление `1577e01e` теперь входит в установленный веб на3015.
На PH011/Android9/Agent1.2.49-dev записаны tap → выбранный XPath → tap → Back.
Все четыре строки сохранились в порядке, запись не остановилась с clock error.
Back получил подтверждение APK469мс; подготовительный Home682мс. Эти значения
относятся к ответу команды, не к появлению видеокадра. Tap имеет только WS
submission outcome; XPath — будущий явно выбранный шаг, Android его не нажимал.

После Stop явная «Вставить в граф» перенесла четыре действия и две паузы
49298/13110мс. Gap меньше100мс не создал sleep. Canonical JSON показывает
9узлов/8success-связей, включая исходные3узла; queue стала0/200.
Node timeout30000мс у длинной паузы не объявлен новым дефектом: установленный
DagRunner повышает sleep budget до ms+3000. Полный replay этой версии не запускался;
global DAG deadline продолжает действовать.

Тестовый graph change отменён одним Undo: v1/3узла/2связи/Undo0, затем выбран
View, laboratory закрыта, временная вкладка закрыта. Save и Run не нажимались.
Чистая пользовательская вкладка обновлена; показывает UI60be6ecd и прежнюю v1.
Ошибок console в проверочной вкладке0. Viewport не менялся.

## Доставка и проверки

Образ получен из успешного [Frontend CI37859419940](https://github.com/RootOne1337/sphere-platform/actions/runs/37859419940).
ZIP120877495bytes, SHA256 `a90780efc43e131f8afecff7d3199ee0aac8ccf6db3c8c73443dcc97bf669b23` совпал с GitHub artifact
metadata. Config ID независимо прочитан из authenticated CI job log;
downloaded receipt и admitted OCI archive связаны с ним до загрузки.
Два config/manifest IDs различаются по OCI формату и проверены через manifest,
а не отключением сравнения. Local npm/Docker build не выполнялся.

| Проверка | Результат |
| --- | --- |
| CI exact60be6ecd | Frontend/Backend/Android/Preview success |
| Frontend CI | 1938tests/139suites, types/build,26pages/73assets |
| CI config ID | `sha256:58746d6466feaa498c9e58e1e29bf63b54a32ec26e9e9d87ed7603cacae70e04` |
| Installed containerd manifest | `sha256:70b7703d44e492d8d1df1422f217522ac09c2b2d11c51bc9eb16e4ab55814a7b` |
| Compose | Только review-ui image/build removal; полный baseline roundtrip |
| Runtime | Healthy,3015/login200;45other containers ID/image/start/state сохранены |
| OTA catalog | SHA256 `5d5dcb5521277b51f366ea5370a2f7df5fd62696de0d5b7b86a56b443b03af10` сохранён |
| Schema/API/APK | Без замены; PH01110249 — конечный canary, не Fleet inventory |
| Host gate | Findings0; один C:free reading50305200128bytes, не скорость/атрибуция |

Private evidence: `.local-pilot/clock-delivery-20261009-60be6ecd/` (bounded archive,
CI log, DOM-backed canonical JSON и screenshots),
`.local-pilot/reviewed-web-install-60be6ecd0b13-d95d94b2/installed.json`.
Предыдущий [source receipt](STUDIO-RECORDER-CLOCK-FIX.md) остаётся неизменённым.

## Оставшийся объём

Live canary не установил, пришёл ли ACK строго после Stop: confirmed виден в
конце короткой последовательности. Late ACK после Stop доказан компонентной
регрессией с контролируемыми часами; это различие сохранено в JSON.
Изменение wall clock живого ПК не выполнялось. Исходные clock-skew fixtures
проверяют epoch1791500000000 и1000 отдельно.

Запись MOVE траектории, automatic tree/crop/pixel bundle и Unicode/IME остаются
OPEN. Idle timeout, global input ownership и storage collector coverage тоже
не закрыты. При default1280×720 «Весь граф» для9узлов слишком мелок: визуальный
finding EP-048 сохранён, функциональный перенос его не закрывает.
Product ledger **9принято/41открыто**, EP-018 OPEN/PARTIAL. CHAT-07 принят только
в указанном конечном scope. Новая documentation revision получает собственный CI.

[Действующий реестр](../../operations/WORK-STATUS.md) ·
[Workbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx) ·
[Recorder](../../../frontend/src/features/scripts/studio/recording.ts) ·
[Sleep timeout guard](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt).
