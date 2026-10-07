# PH025: отказ первого видеокадра и выбор декодера

Дата: 8 октября 2026, Asia/Yekaterinburg. Область: выделенный viewer на 3015,
реальный поток PH025, WebCodecs AVC и диагностика браузера.

## Подтверждённая причина

После получения настоящих IDR/delta packets установленный viewer передавал
данные в VideoDecoder, но не получал ни одного output. Изолированный прогон
на этом же браузерном хосте воспроизвёл `OperationError` при принудительном
`hardwareAcceleration: prefer-hardware`. Сообщение native decoder указывало
на неподдерживаемую конфигурацию. Это не доказательство неисправности GPU:
конкретная причина недоступности аппаратной реализации не установлена.

Один и тот же конечный набор из 16 реальных packets PH025 проверен тремя
режимами. Codec в каждом случае — `avc1.42C01F`, разрешение 960 × 540;
SPS/PPS, frame payload, AVCC conversion и путь canvas были одинаковыми.

| Выбор реализации | Submitted | Outputs | Drawn | Decode errors |
| --- | ---: | ---: | ---: | ---: |
| prefer-hardware, исходная политика | 1 | 0 | 0 | 1 |
| no-preference | 11 | 11 | 11 | 0 |
| prefer-software, контроль | 11 | 11 | 11 | 0 |
| Текущий исправленный source, no-preference | 11 | 11 | 11 | 0 |

Fixture содержит 2 IDR и 9 delta pictures, 3 SPS и 2 PPS, всего 105833 bytes.
Это конечный диагностический набор с искусственным темпом подачи. Его FPS
не является измерением live FPS, latency, доступного битрейта или GPU load.
Прогон использует настоящий VideoDecoder браузера, не mock. Текущий source
отдельно transpiled и проверен после изменения, baseline сохранён отдельно.

## Изменение

- [H264Decoder](../../../frontend/lib/h264-decoder.ts) выбирает `no-preference`:
  браузер может использовать доступную поддерживаемую реализацию.
  `optimizeForLatency`, очереди, age limits, reference recovery и frame identity
  сохранены. Software decoder не навязывается всем устройствам.
- Статистика содержит одну последнюю allowlisted причину отказа. Для неизвестных
  имён используется `OtherError`; произвольные сообщения/stack не сохраняются.
- [DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx) выводит
  код в раскрываемой диагностике. Историческая последняя ошибка не означает,
  что восстановившийся stream по-прежнему неисправен: это последнее событие.
- [Регрессии](../../../frontend/__tests__/stream/h264-decoder.test.ts) проверяют
  аппаратный отказ, bounded diagnostic code и игнорирование retired callback.

WebCodecs определяет выбор ускорения как hint и допускает изменение доступности
реализации во время работы. Политика по умолчанию — `no-preference`.
[Первичный источник: W3C WebCodecs](https://www.w3.org/TR/webcodecs/).

## Проверки и границы доказательств

Три новые регрессии сначала упали на исходном коде, затем прошли с исправлением.
Leaf: 42 passed. Полный frontend: 1820 passed, 137 suites. Fresh Next typegen
и полный non-incremental TypeScript прошли. Точные hashes и scalar результаты
браузерного прогона находятся в [evidence](PH025-DECODER-RECOVERY-EVIDENCE.json).

В расследовании использованы два адресных stop/start capture только PH025,
чтобы получить конечный набор настоящих pictures. ОС, эмулятор, backend и APK
не перезапускались и не обновлялись. Fixture сохранён только в приватной
`.local-pilot`, с ограничением bytes/count/deadline; он не входит в Git/PR.
Application screenshots, токены и сообщения произвольного driver не публикуются.

На момент source validation установленный UI — af9054e, API — a41c4e6;
PH025 APK — 10245, PH010 — 10247. Source validation ещё не означает успешную
установку на 3015. Следующий обязательный шаг — exact-source hosted frontend CI,
admission проверенного runtime artifact, установка только review-ui и fresh
браузерная приёмка живой карточки PH025. Результат установки записывается
отдельным последующим срезом, исходные результаты не переписываются.

## Независимое оставшееся условие

До capture restart на статическом экране наблюдались SPS/PPS без новых VCL
pictures. Запрос IDR сам по себе не заставляет planar encoder получить новый
raw frame. Это отдельное условие late viewer/static capture и не объявляется
исправленным сменой decoder hint. Повторное подключение и статический первый
кадр требуют самостоятельной проверки. Непрерывный input также не включён в
установленном viewer; соответствующие scoped routes, receipts и end-to-end
приёмка остаются открытыми в [текущем состоянии](../../operations/CURRENT-STATE.md).
