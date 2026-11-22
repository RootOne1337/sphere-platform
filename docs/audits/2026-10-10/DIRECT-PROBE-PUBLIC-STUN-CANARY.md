# Public STUN: один native canary и проверенный возврат

10 октября 2026. Source `934f46a8` прошёл четыре exact-source CI, подписанный
APK того же package/version/certificate проверен до установки только на PH011.
Это диагностический echo-only профиль. Видео, касания, fleet OTA и APK1.3 не приняты.

## Что установлено измерением

Browser offer содержит application-only SDP: host1/mDNS1 и srflx1, relay0.
Ограниченный Redis observer зарегистрировал offer и через7,989s close, без answer.
UI показал signaling deadline; echo0/20, RTT и selected pair неизвестны.
Поздний screenshot03:08UTC показывает обзор карточки, а не экран отказа; он не
считается доказательством текста ошибки. Независимый durable observer сохраняет
только типы сообщений/кандидатов и elapsed время, без SDP/IP/session/ключей.

APK загрузил JNI, создал native factory/threads. Native reports0 не означают,
что PeerConnection не создавался: исходный934 начинал getStats только после answer.
Конкретный этап до answer неизвестен. Это не доказанная ошибка NAT, mDNS, STUN,
VPN или TURN; переходить к такой причине по одному отсутствующему ответу нельзя.
Предыдущий host-only8447 получил answer и является отдельным срезом.

## Время и возврат

Диагностический APK установлен01:39:46UTC; probe выполнен около01:41:44UTC.
Из-за прерывания работы возврат завершён после возобновления: исходный APK
восстановлен03:08:10UTC, backend gate выключен03:09:09UTC с пустым allowlist.
Одна peer-сессия имеет30s невозобновляемый lease; это не длительность установки APK.
Raw logcat использует другое отображение часов, его нельзя вычитать из browser clock.

UI639/API369 сохранены по source/image. API пересоздан, новый container epoch
записан в JSON;45соседних контейнеров/schema/OTA сохранены. Данные приложения не
очищены, другие устройства не обновлялись. Временные3016/3017 и тестовые вкладки закрыты.

После возврата read-only health/build/device проверки прошли локально и через
туннель, PH011 online; выключенный probe отклонён4003. Обычный view-only viewer
получил public25/local24 decoded/drawn frames, invalid/decode/render0 в конечных
срезах. Это не длительный FPS/idle/input benchmark. Capture telemetry и viewer
имеют разные моменты наблюдения; stale not_streaming не подменяет frame counters.

## Следующий исправляемый пробел

Добавить фиксированные bounded native этапы до answer и getStats во время setup.
Затем source/test/signed/CI admission и один новый конечный probe без изменения
deadline. Только измеренный этап определит, нужен ли trickle ICE, исправление
SDP/native failure или другой сетевой профиль. Простое увеличение таймаута не принято.

[Машиночитаемый receipt](DIRECT-PROBE-PUBLIC-STUN-CANARY.json) ·
[Исходный source scope](DIRECT-PROBE-STUN-PROFILES.md) ·
[План транспорта](../../design/BROWSER-DIRECT-TRANSPORT.md) ·
[Действующий остаток](../../operations/WORK-STATUS.md).
