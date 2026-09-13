# Падение Android при остановке и повторном захвате экрана

**13 сентября 2026 · AUD-112 · High operational · native crash и regression до/после.**

[Аудит](AUDIT-REPORT.md) · [Транспорт видео](STREAM-VIDEO-ROUTING.md)

## Инцидент и влияние

После исправления server video routing изображения обоих Android появились в
вебе, но повторный захват/остановка выявили падение **всего процесса APK 1.2.4**.
Владелец также подтвердил диалог «В приложении Sphere Agent снова произошёл сбой»
на обоих LDPlayer. Просмотры остановлены; native crash buffer сохранён без очистки.
Успешное декодирование отдельных кадров не является приёмкой стабильного стрима.

Оба устройства: Android 9 / API 28, LDPlayer 9.5.6.0, APK `fdd26c5` / 10204.
Crash thread `sphere-imagerea`: **SIGSEGV → libc memcpy →
Bitmap_copyPixelsFromBuffer**. На первом устройстве сохранены падения в 20:28:00,
20:29:44, 20:29:47 и 20:32:41 по часам Android; второй имеет аналогичные сигнатуры.
Время Android отличается от host UTC; нельзя смешивать эти timestamps для latency.

## Root cause и воспроизведение

`StreamingManagerImpl.start()` ставит image callback на `HandlerThread`.
`stopInternal()` из service/main потока выставлял `streaming=false`, затем
закрывал `ImageReader` и перерабатывал cached Bitmap, **не дождавшись callback**.
Callback проверял `streaming` только перед draw; acquire/copy происходили раньше.
`quitSafely()` не ожидал завершения текущего native copy. Поэтому native storage
мог освобождаться во время `copyPixelsFromBuffer`; Java catch не ловит SIGSEGV.

`StreamingCaptureLifecycleTest` вызывает реальный manager/listener с Robolectric
и MockK на Android native boundary. Latch удерживает copy активным, пока другой
настоящий JVM thread вызывает stop. **До: оба исходных теста падают**:

1. Reader закрывается во время активного copy (не просто после его возврата).
2. Callback из старой очереди вызывает acquire/copy уже после stop.

Native stack подтверждает реальное падение в этом пути; детерминированный тест
подтверждает конкретное нарушение владения ресурсом. Он не исполняет Android C++
memcpy и сам по себе не заменяет native повтор после исправления.

## Исправление

Lifecycle start/stop сериализуется. Общий frame lock защищает весь acquired Image
до `image.close()`, включая native copy и draw; закрытие reader и recycle bitmap
выполняются под тем же lock. Перед закрытием снимается listener. Callback проверяет
идентичность capture session, поэтому очередь старого HandlerThread не трогает
ресурсы после stop или нового start. Canvas освобождается в finally. Устаревший
encoder error callback не перезапускает уже другую capture session.

Affected: `android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt`.
Regression: `android/app/src/test/kotlin/com/sphereplatform/agent/streaming/StreamingCaptureLifecycleTest.kt`.
Дополнительно проверяются callback после restart и повторный idempotent stop.
APK version повышается до **1.2.5 / 10205** для проверки OTA; LATEST меняется
только после build/signature/install/runtime acceptance.

```sh
cd android
./gradlew :app:testDevDebugUnitTest --tests '*StreamingCaptureLifecycleTest'
```

## Residual risk и статус

**Full Dev JVM: 560 tests / 42 suites / 0 failures, errors, skips**, включая
четыре capture regressions. Подписанная pilot build, OTA и native capture
repetition оформляются отдельно. [Результаты](evidence/android-capture-lifecycle-summary.json).
Лимит памяти/нагрузки при сотнях просмотров, Android 14/15 projection restrictions
и зависание vendor surface/codec не считаются проверенными. Stop должен дождаться
уже выполняющегося native frame operation; замеры длительности stop нужны на
реальном устройстве. Root и восстановление APK после crash не устраняют сам crash.
