# Studio: следующая работа по записи и живому управлению

8 октября 2026, Asia/Yekaterinburg. **Recorder и viewer-local task handoff установлены / P1 OPEN**.
Explicit recorder mode принят наPH011; task preparation5382fe4 проверен двумя
реальными3-step tasks. Богатая запись/global lease открыты. После простоя
повторился native receipt timeout; этот P1 важнее расширения визуальных форм.
[Приёмка task preparation](STUDIO-TASK-INSTALLED-ACCEPTANCE.md) ·
[Idle failure](STUDIO-IDLE-RECEIPT-FOLLOWUP.md).
Выявлен source defect потери task/recording/unknown-POST state при same-session
token refresh; UI36b160f9 установлен, живой refresh ещё не засвидетельствован:
[session-state follow-up](STUDIO-SESSION-REFRESH-STATE.md).
API be803773 установлен: failed viewer send изолирован, независимый Android
View подтвердил drag/wheel. Idle receipt loss повторился и остаётся P1.
Отдельно transient capability failure при API restart потерял laboratory state
без F5. UI46ca2096 теперь установлен:72s API outage сохранил PH011/View,
completed task с3отчётами/marks и PH011/priority8 в launch portal без F5.
Все4 CI successful; frontend1915/138suites, backend3346passed/37skipped/
229subtests. Unknown POST/dirty queue/aborted native PNG fence проверены
fixtures отдельно. Это исправляет retention, но не idle failure/global lease.
[Новый контракт и проверки](../2026-10-09/STUDIO-PERMISSION-OUTAGE-RETENTION.md).
[Fault isolation и наблюдение](CONTINUOUS-VIEWER-FAULT-ISOLATION.md).
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
2. Viewer-local task preparation и конечная canary — приняты отдельно; далее
   bounded диагностика повторного idle receipt loss, global ownership и unknown POST.
3. Versioned observation manifest + native snapshot bundle, storage/RBAC limits.
4. Review UI для XPath/crop/pixel с подтверждённой provenance каждой части.
5. Playback корреляция node attempt/input/frame с измеренными clock границами.
6. Remote/fleet faults и bounded soak, затем массовое включение по capability.

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

## Installed task checkpoint07:49–08:06UTC

UI5382fe4: one pinned POST follows known owned release and read/capture drain;
failed/aborted preparation is distinct from an uncertain POST result.237 local
regressions and all4 hosted workflows passed. Two real saved-v1 tasks completed;
second root cleanup finished32ms before task creation. A later idle timeout
required explicit recovery; finite240/240service ACK timings did not explain it.
Global ownership, durable reconciliation and rich observations remain OPEN.
