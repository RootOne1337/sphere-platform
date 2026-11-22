# APK: владение MediaCodec output при stop и ошибке callback

Дата: **1 октября 2026**, Asia/Yekaterinburg. Версия исходников: **1.2.40 / 10240**.
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Codec-input canary](../../operations/CODEC-INPUT-CANARY.md) ·
[Android guide](../../android-agent.md) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

## Подтверждённые дефекты исходников

`H264Encoder` проверял принадлежность input callback, но не output/error callback.
После stop запоздалый output мог обращаться к освобождённому MediaCodec, config
мог заполнить SPS/PPS следующей сессии, а старый error — запросить лишний restart.
`onFrameReady` вызывался до `releaseOutputBuffer` без finally: исключение
потребителя оставляло output buffer невозвращённым. Само исключение native
read/release могло уйти из callback thread.

Google требует возвращать использованный output buffer кодеку; native read и
release допустимы в Executing state. Отсюда следует необходимость согласовать
эти операции с stop, а не обращаться к индексу после освобождения кодека.
[MediaCodec API](https://developer.android.com/reference/android/media/MediaCodec#releaseOutputBuffer(int,%20boolean)),
[callback API](https://developer.android.com/reference/android/media/MediaCodec.Callback#onOutputBufferAvailable(android.media.MediaCodec,%20int,%20android.media.MediaCodec.BufferInfo)).

## Исправление

1. Output принадлежит только текущему объекту кодека. Его native read/release
   сериализованы с stop через существующий input lock.
2. Копия байтов принадлежит приложению. Native buffer возвращается **до** внешнего
   потребителя кадра. Внешний callback выполняется **без** input lock, сохраняя
   порядок locks StreamingManager и возможность синхронного stop у потребителя.
3. Read/release exceptions содержатся внутри callback. Первичная причина
   сохраняется; дополнительная ошибка release прилагается как suppressed.
4. Error от текущего кодека передаётся менеджеру один раз на его жизненный цикл,
   с исходным exception. Старый error не инициирует recovery новой сессии.
   Исключение подписчика error также не выходит в Looper.
5. Stop очищает SPS/PPS; успешный config продолжает немедленно отправлять NALs.
   Между отправками NALs проверяется актуальность кодека. Дополнительный session
   fence менеджера сохраняется.

## Проверка

Восемь первичных сценариев: **7 воспроизведённых assertion/exception failures**;
один исходный тест встретил ограничение MockK для CodecException. После замены
fixture на реальный Robolectric exception этот восьмой сценарий также воспроизвёл
ложное уведомление об ошибке после stop. Это различие сохранено в записи проверки.

После исправления все **13 callback ownership tests** проходят, включая bytes
offset/copy после release, stop из SPS consumer, двойную ошибку read/release,
exception подписчика и единственное recovery notification.
Полные Dev и Enterprise debug suites: **783 tests каждый / 782 passed / 1 skipped /
0 failures / 0 errors**. Dev APK собран. Конфигурируемый подписанный pilot artifact,
OTA readback и runtime проверка записываются отдельно; обычный debug assemble
не объявляется установленной версией.

## Подписанный canary и native readback

Configured source **68155c1**, **1.2.40-dev / 10240**, прежний pilot signer/package,
8465471 bytes, SHA256
`c612fba1e4a537ab1a0d9951e520bbd4063c3548308a4ebc31b72b59fa735a70`.
Обе полные configured debug suites 783 также прошли и обе APK собраны.
Адресные OTA PH010/PH025 completed, installed 10240, process-restart recovery
и свежие online versions подтверждены. Normal/global OTA не продвигалась.
Android source tree совпадает с принятым 8d64ca4:
[Android CI 36864314903](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314903)
passed variants/tests/signed release smoke. Release smoke не является подписью
этого pilot artifact production key.

В finite native trial PH010 — 299 pictures/10 s; remote PH025 остаётся 5 Hz и
имеет длинные startup/gaps. Post-encoding snapshot зафиксировал zero encoder
errors/input drops, но поздний snapshot старый: нули не относятся ко всему trial.
[Полная методика, receipts и JSON](CALLBACK-LIFECYCLE-CANARY.md).

## Открытые границы

- Эти source regressions не доказывают, что callbacks были причиной низкого FPS
  PH025. Последнее установленное измерение remote cadence остаётся в
  [codec canary](../../operations/CODEC-INPUT-CANARY.md).
- Planar input пока debug canary; defaults и release gates сохраняются.
- `StreamingManagerImpl` пытается восстановить codec через повторный start с
  прежней MediaProjection. Для Android 14+ повторное использование projection
  session требует отдельного recovery-контракта и native acceptance;
  lifecycle fix буферов не объявляет эту ветку принятой.
- Browser draw/input latency, долгий CPU/RAM бюджет и массовый stream+script
  прогон остаются открытыми [readiness gates](../../operations/READINESS.md).
