# Studio: следующая работа по записи и живому управлению

8 октября 2026, Asia/Yekaterinburg. **Этап1 установлен / остальное OPEN / P1**. Explicit recorder mode принят
наPH011; богатая запись и task-launch handoff ещё открыты.
Канонический audit ledger остаётся9accepted/41open; это уточнение существующих
SF26-05/06, а не новая заявка о закрытии всей автоматизации.

## Исторический дефект baseline9610523 в лаборатории

[DeviceWorkbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx)
передаёт `onControlSent={sent}` и `onControlCommand={commandObserved}` постоянно,
в том числе когда `recording=false`. Callback сохраняет существующие receipts
и close guards; простое снятие observer после Stop может потерять поздний ACK.

Baseline [DeviceStream](https://github.com/RootOne1337/sphere-platform/blob/961052334b99f9a27fa292f5217d5d0130dd6094/frontend/components/sphere/DeviceStream.tsx) выводил
`continuousRecording = !!onControlSent || !!onControlCommand` и запрещает
continuous input при таком значении. Поэтому normal control внутри Studio
постоянно использует discrete fallback, хотя тот же PH011 поддерживает native
continuous gestures в карточке устройства. Источник и условие были подтверждены. Вa8945e4 условие исправлено;
normal mode, запись, late ACK после Stop и возврат READY приняты отдельно:
[installed acceptance](STUDIO-RECORDER-INSTALLED-ACCEPTANCE.md).

Исправление должно разделить **намерение записывать дискретные действия** и
**подписку на результаты команд**. Explicit recording mode предпочтительнее
удаления observer. Start/Stop во время pointer down требует known native release;
не переносить неизвестный DOWN в новый режим и не выдавать ложную готовность.
Auth/device/window invalidation, stale receipts и ordered review buffer
сохраняются. Отдельная кнопка включения живых жестов пользователю не нужна.

Приёмка: normal workbench READY/MOVE до UP, Start→дискретная запись, Stop→READY;
late key/text ACK обновляет исходный slot после Stop; live gesture при смене
режима завершается без replay/duplicate; pending release не допускает нового
input. Нужны component/controller regressions и реальный PH011 browser canary.

## Расширенная запись: отдельный режим и проверяемые данные

[Recording model](../../../frontend/src/features/scripts/studio/recording.ts)
сейчас ограничен200 действиями. Click/swipe имеют transport-submitted outcome;
key/text — APK pending/confirmed/unknown; selector — planned, не исполненный.
XPath хранит snapshot ID/node ID/rotation только временно в review context,
при вставке исполняемого selector observation context не становится artifact.

Для спецрежима пользовательского запроса нужны отдельные observations:

| Источник | Что сохранять | Чего не утверждать |
| --- | --- | --- |
| Native touch | coordinates/path/duration, owner/epoch, submission/receipt times | ACK не является visual result |
| UI hierarchy | snapshot ID, requested/completed times, geometry/rotation, выбранный узел | независимое дерево не atomic с видео |
| Native PNG | оригинальный SHA256/dimensions/times, crop rectangle | H.264 frame не пиксельный эталон |
| Pixel sample | original coordinates, RGBA, reported/unknown color space | DPI не доказывает byte/pixel identity |
| Execution | task/run/version/node/attempt, terminal ACK, postcondition | отсутствие лога не success |

Нужен scoped observation manifest отдельно от executable DAG action, bounded
artifacts/retention, явное opt-in для private text/images, RBAC/scoping и
отказные статусы каждой части. Частично полученный bundle не становится полным.
Snapshot diagnostic ID помогает связать конкретный failed read с сервером:
[UI inspection diagnostics](UI-INSPECTION-DIAGNOSTICS.md).

Native capture ранее занимал несколько секунд. Нельзя незаметно добавлять
его перед каждым живым нажатием и обещать прежнюю latency. Spec recording
должен иметь явную готовность evidence, возможность отмены и запрет повторного
input при неизвестном ACK. XPath выбор, planned action и реальное нажатие —
разные действия, их timeline не должен переставляться.

## Последовательность

1. Explicit recorder/observer handoff и установленный normal-control canary.
2. Versioned observation manifest + native snapshot bundle, storage/RBAC limits.
3. Review UI для XPath/crop/pixel с подтверждённой provenance каждой части.
4. Playback корреляция node attempt/input/frame с измеренными clock границами.
5. Remote/fleet faults и bounded soak, затем массовое включение по capability.

Не заявлены покадровая синхронизация, zero latency, rich evidence или durable
continuous trajectory recording. [CURRENT-STATE](../../operations/CURRENT-STATE.md)
сохраняет фактические installed/accepted границы.

## Prepared implementation checkpoint

Explicit recording mode, native-release readiness, bounded unknown-release
fence and late observer preservation implemented.201 local regressions and
TypeScript passed; installed acceptance pending.
[Behavior, source tests and remaining task handoff](STUDIO-RECORDER-MODE.md).

## Installed checkpoint07:15UTC

UIa8945e4 installed; normal native View gesture, discrete recording, late
Home ACK after Stop and return to READY verified on PH011. Source tests and
finite installed evidence remain separate. Task-launch handoff/rich recorder
stay OPEN. [Installed acceptance](STUDIO-RECORDER-INSTALLED-ACCEPTANCE.md).
