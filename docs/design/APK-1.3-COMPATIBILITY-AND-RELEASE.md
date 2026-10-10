# APK 1.3.0: совместимость, расширение и критерии выпуска

Сверено 10 октября 2026, UTC+5, по исходникам PR19. Это план и аудит текущих
контрактов, не объявление stable release. VERSION_NAME=1.2.51,
VERSION_CODE=10251 в source и signed сборке; адресный OTA PH030 выполнен, actual package SHA совпал. PH011 сохраняет ordinary private1.2.49-dev. PH030 получил
read-only video canary1.2.51-dev; это не приёмка основного direct media/input.
Повышение номера без закрытия runtime gates не является стабилизацией.

Дополнение10октября04:16UTC: exact161 diagnostic APK прошёл4CI/signed admission,
native setup/pre-answer stats и один UID-filtered packet capture. Ответы быстрые,
но прямой канал не открылся; original1.2.49-dev восстановлен, OTA не менялась.
Это не stable1.3 gate. [Фактическая проверка](../audits/2026-10-10/DIRECT-PROBE-NATIVE-PROGRESS-CANARY.md).

[Действующие работы](../operations/WORK-STATUS.md) ·
[Установка](../operations/CURRENT-STATE.md) ·
[Прямой транспорт](BROWSER-DIRECT-TRANSPORT.md).

## Что уже расширяется без переустановки APK

| Возможность | Текущий механизм | Граница |
| --- | --- | --- |
| Новый сценарий из существующих действий | Backend versioned DAG → локальный DagRunner | Новое native действие требует кода APK |
| Изменение параметров и логики | DAG nodes, variables, condition, Lua и HTTP action | Допустимые параметры и доступ определяет установленный runtime |
| Новый серверный ingress | ConfigWatchdog / signed discovery / сохранённые routes | Не меняет произвольно native протокол, signer или Android permissions |
| Обновление веба и API | Отдельные доставляемые артефакты | Совместимость команд нельзя выводить только из номера APK |
| Обновление самого APK | Проверяемый OTA artifact | Нужны тот же package/current signer set и больший versionCode |

Сценарии исполняются локально на Android, браузер не обязан быть открыт.
Серверное согласование владения нужно для интерактивного управления; новый direct
transport не должен отменять task ownership, tenant/RBAC, epoch или отзыв доступа.

## Проверенные текущие границы

- Gradle: minSdk26, compile/targetSdk35. Поддержка других API levels/эмуляторов
  не выводится из успешного теста на одном устройстве.
- continuous offer: protocol_version1 / frame_protocol_version2, capture_epoch,
  frame/physical geometry, rotation, display0, max_pointers1. Offer сообщает
  injector_ready=false; только native startup receipt разрешает ready.
- Browser controller: один pointer, одна несброшенная MOVE, максимум32 scalar
  receipts. DOWN/terminal не ставятся в очередь для повторения после reconnect.
- Local DagRunner: node/depth/loop-log/output bounds и ограниченные timeouts.
  CommandJournal ограничивает сохранённую историю; это не exactly-once для любого
  внешнего приложения или HTTP side effect.
- FileLoggingTree: пять файлов по2MiB, очередь256, одна запись до16KiB;
  отдельные lifecycle/read bounds. Эти лимиты не доказывают отсутствие роста
  всего диска Windows, Docker VHD или чужих процессов.
- ConfigWatchdog объединяет повторные проверки в один запрос; lifecycle generation
  и store revision ограждают устаревший ответ. Signed discovery не превращает
  отдельный ingress в полноценную серверную HA.
- OtaApkVerifier проверяет downloaded package, versionName/versionCode, minSdk,
  точный current signer set. Ротация ключей требует отдельного promotion policy;
  общий ancestor signer не принимается как достаточное доказательство.

Источник фактов: android/app/build.gradle.kts; commands/ContinuousInputController.kt,
ContinuousTouchSupervisor.kt, DagRunner.kt, CommandJournal.kt; logging/FileLoggingTree.kt;
service/ConfigWatchdog.kt; ota/OtaApkVerifier.kt; frontend/src/features/stream/continuousPointer.ts.
Kotlin пути указаны относительно android/app/src/main/kotlin/com/sphereplatform/agent/.

## Важное различие private canary и stable APK

CONTINUOUS_INPUT_CANARY, STREAM_PLANAR_INPUT, GPU_BRIDGE и DIRECT_TRANSPORT_CANARY
защищены от release-shaped Gradle task при включённых экспериментальных flags.
Direct probe добавляется отдельным debug source set; JNI не входит в обычную
сборку. Снятие этих запретов без native/browser/resource acceptance недопустимо
в рамках этого плана. Private pilot certificate/package не являются production
identity; APK с другого signer нельзя распространять как обычное OTA обновление.

Две попытки host ICE дали JNI load и SDP answer, но не открыли DataChannel:
RTT неизвестен, endpoint снова отключён, исходный APK восстановлен.
Повторяющийся idle_receipt_timeout также OPEN. Поэтому 1.3.0 сейчас NO-GO.

## Предлагаемый versioned capability contract

Не реализован этим документом. Нужен единый descriptor APK → API → web с
явными protocol major/minor, action schema revision/hash, supported action IDs,
capture/input profiles, permission/root state, build revision и resource limits.
Список возможностей должен быть bounded и привязан к текущей authenticated
agent connection generation; старый heartbeat не разрешает новое управление.

Web показывает поддерживаемость каждого действия на выбранном устройстве до
запуска. API сохраняет pinned script version и требования; APK повторно проверяет
их перед side effect. Отсутствие descriptor означает unknown/legacy profile,
а не поддержку всего каталога. Серверная валидация графа не подтверждает наличие
XPath элемента, Android permissions или успешное выполнение native action.

| Изменение | Предлагаемое правило | Проверка |
| --- | --- | --- |
| Новое необязательное capability | Явный minor/profile extension | Старый клиент сохраняет ограниченный профиль |
| Новый native action | Отдельный ID и schema revision | Unsupported отклоняется до side effect |
| Изменение смысла existing action | Новый incompatible revision | Нет тихой смены старого сценария |
| Input wire extension | Явная negotiation/version branch | Strict parser старой версии не ослабляется |
| Смена capture/rotation/socket | Новая generation и повторная готовность | Старые координаты/ACK не принимаются |
| Отзыв доступа/смена владельца | Fencing и подтверждённый release | Поздний ответ не оживляет старую сессию |
| Direct path недоступен | Видимый выбранный fallback | Не объявлять relay прямым соединением |

Descriptor сообщает техническую возможность, но не заменяет authorization.
Конфигурация не должна загружать произвольный native executable или обходить
permission/signature проверки ради «APK больше никогда не обновлять».
AI-клиент использует те же versioned APIs, execution receipts и screenshots;
права на side effects остаются явными и журналируемыми.

## Release gates для 1.3.0

| Gate | Текущее состояние | Доказательство для перехода |
| --- | --- | --- |
| Повторяющийся idle ACK failure | OPEN | Локализован участок задержки; finite local/public canary и заданный soak без ручного восстановления |
| Native continuous lifecycle | PARTIAL | UP/CANCEL/blur/hidden/owner/task/reconnect/rotation, no held pointer after loss |
| Direct media/input | PROTOTYPE, не installed | Real ICE path, media+input timing, TURN fallback, auth/revocation/network matrix |
| Native resource lifetime | OPEN | Повторные open/close/cancel, RSS/JNI/thread/FD budgets и cleanup evidence |
| Recorder continuous trajectory | OPEN | Траектория и Android keys совпадают с подтверждёнными действиями; replay semantics явны |
| Version compatibility | PARTIAL | Старый APK/new API, новый APK/old API, unsupported action и upgrade tests |
| Production signing | REQUIRE_VERIFICATION | Настроенный production signer, certificate continuity и install receipt |
| OTA promotion | PARTIAL | Download/hash/package/version/signer/permission/restart/failure матрица на candidate |
| Resource/storage retention | OPEN | Ограниченные logs/cache/results; подтверждённое наблюдение роста под нагрузкой |
| Documentation/runtime alignment | CONTINUOUS | Exact artifact/source/runtime revisions и неизменяемый finite receipt |

Direct migration может иметь отдельный controlled rollout; нельзя выпуском1.3
приписать новой версии незавершённые возможности. Перед выбором scope stable
фиксируется конкретный профиль, обязательные gates и поддерживаемые устройства.

### Локальная сеть при будущем targetSdk37

Текущий source использует targetSdk35. По официальной инструкции Android17
приложение при переходе на target37 должно отдельно согласовать разрешение
локальной сети и обрабатывать отказ/отзыв перед LAN/UDP/mDNS connection.
Для текущего target35 инструкция запрещает преждевременный запрос нового
permission; manifest здесь не меняется. Проверочный PH011 — Android9/API28,
поэтому новая защита не является установленной причиной его ICE failure.
[Android local network protections](https://developer.android.com/privacy-and-security/local-network-permission).
Target bump, permission UX и network denial/revocation tests — отдельный
compatibility gate, не обещанная возможность stable1.3.

## Практический порядок выпуска

1. Закрыть idle/native lifecycle в выбранном профиле и зафиксировать latency/resource
   budgets. Одно увеличение heartbeat deadline не доказывает устранение задержки.
2. Принять отключённый direct canary, затем media/input integration отдельным этапом.
3. Проверить обе стороны compatibility и согласованные release flags.
4. Увеличить versionName до1.3.0 и выбрать strictly greater versionCode согласно
   фактическому installed/catalog максимуму; текущий10249 не вечная верхняя граница.
5. Exact-source test/lint/signed build и проверка actual package/certificate/SHA.
6. Сначала один согласованный pilot device; сохранить rollback artifact/data plan.
   OTA downgrade не поддерживается: возврат меньшей версии не обещается как штатный.
7. После finite acceptance и soak — staged catalog promotion с наблюдаемыми outcomes.

.github/workflows/release.yml требует vX.Y.Z, совпадения source version, ancestry
в main, непустых signing inputs, test/lint/assembleEnterpriseRelease и проверки
package/version/certificate. Наличие всех production secrets в этом срезе не
проверено. Tag, публикация1.3.0 и замена установленного APK здесь не выполнялись.
