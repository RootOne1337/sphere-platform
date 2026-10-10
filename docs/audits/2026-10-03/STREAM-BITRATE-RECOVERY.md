# N07 — восстановление целевого битрейта после переполнения локальной очереди

Дата: 3 октября 2026, Asia/Yekaterinburg. Это продолжение проверки APK и
[F36](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f36); исходный аудит не изменён.

[Current State](../../operations/CURRENT-STATE.md) ·
[Evidence JSON](STREAM-BITRATE-RECOVERY-EVIDENCE.json) ·
[Реестр исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Публикация OTA и проверка APK](../../operations/OTA-PUBLICATION-AND-APK-CHECKS.md)

## Доказанная ошибка

В исходном `AdaptiveBitrateController` повышение вычислялось как +5%, но
применялось только при разнице **строго больше 100 000 бит/с**. Поэтому любой
текущий target ≤2 000 000 бит/с переставал восстанавливаться. Production encoder
стартует с 1 500 000 бит/с; после первых трёх отказов локальной WebSocket-очереди
target становился 1 200 000. Предложенное повышение до 1 260 000 отбрасывалось.
После восстановления связи контроллер мог оставаться на 500 000 до конца сеанса.

Это ошибка алгоритма, которая способна ограничивать качество. По ней нельзя
объявить установленной причину конкретного FPS, input latency или сетевого обрыва.
Нет записанного live congestion trace с фактическим потоком байт старого APK.

Старый тест восстановления вычислял тот же порог и делал assert только если
порог уже пройден. Для 1 600 000 этот блок вообще не выполнялся. Тест reset после
drop также не имел assert, а проверка ceiling разрешала неизменные 3 900 000.
Эти три проверки теперь требуют конкретного результата; добавлены production
default, recovery от floor и конечная последовательность floor→ceiling.

## Воспроизведение и исправление

На базовом source `eafeb3312c6dc359f67cec0550113e4003bc88eb`, до изменения
контроллера, усиленный набор дал **15 cases: 9 passed / 6 failures**.
Все шесть failures — несовпадения ожидаемого восстановленного target, а не
ошибка сборки или fixture. Raw JUnit и Gradle log сохранены отдельно.

После замены условия на `newBitrate > currentBitrate` тот же набор дал
**15 passed / 0 failures / 0 errors / 0 skips**. Debounce 90 локальных admissions,
снижение на20%, floor500000 и ceiling4000000 сохранены. Это один исправленный
алгоритмический порог; сетевые маршруты и codec capture path не менялись.

| Сценарий | До исправления | После исправления |
|---|---:|---:|
| Production1.5M→3 отказы→90 admissions | 1200000 | 1260000 |
| Default2M→3 отказы→90 admissions | 1600000 | 1680000 |
| Floor→90 admissions | 500000 | 525000 |
| Floor→50 последовательных окон90 | 500000 | 4000000 |
| Target3.9M→окно90 | 3900000 | 4000000 |
| 80 admissions→1 отказ→50+40 admissions | 1600000 | 1680000 |

90 — количество принятых локальной очередью пакетов, не wall-clock timer.
При30 media packets/s это приблизительно3 секунды; меньшая source cadence
замедляет восстановление. Queue admission не означает server delivery и не
оценивает реальную пропускную способность удалённой сети.

## Android API и предел доказательства

Используется существующий
[MediaCodec.PARAMETER_KEY_VIDEO_BITRATE](https://developer.android.com/reference/android/media/MediaCodec#PARAMETER_KEY_VIDEO_BITRATE)
для изменения target в бит/с. Официальный
[setParameters](https://developer.android.com/reference/android/media/MediaCodec#setParameters(android.os.Bundle))
может молча не применить некоторые параметры. Поэтому `currentBitrateBps`
контроллера — желаемое значение, а не измеренный encoded bitrate или
подтверждённая поддержка конкретного OMX. Код Native setter этим исправлением
не менялся; containment отказов при параметризации требует отдельной проверки.

Robolectric/MockK regression подтверждает расчёт и вызовы setter. Native codec,
render FPS, server delivery и click→visible latency требуют отдельного live
trace. Подтверждения плавности или enterprise acceptance этим тестом нет.

## Версия и следующие проверки

Исходники подготовлены для кандидата **1.2.42 /10242**. На момент исходного
фиксирующего commit APK42 ещё не собран, не опубликован и не установлен.
Работающий UI77fca37/API facba9a и последний принятый fleet10241 сохраняются.
Полные Android tests/build, сертификат/actual archive, addressed remote upgrade
и свежий heartbeat должны получить отдельные receipts перед rollout.

Следующее успешное обновление10241→10242 также проверит новый APK identity guard
из10241. Normal android/dev10209 пока не продвигается. F33 PARTIAL и F36 OPEN;
реестр остаётся **33 source-fixed /8 OPEN**, поскольку полный profile negotiation
и measured requested/accepted/rendered contract ещё не реализован.

## Доставка ABR fix: финальный readback3 октября

10242 собран/опубликован, но guard10241 отказал наPH028;0 установок42.
N08 исправил совместимость signature metadata. После scoped recovery и одного
успешного штатного43→44 OTA все14online получили10244 с этим ABR fix.
Это доставка исправленного алгоритма, не measured native bitrate/FPS acceptance.
[Полный native/rollout evidence](OTA-SIGNER-COMPATIBILITY.md).
