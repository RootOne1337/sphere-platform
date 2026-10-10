# Автоматическое управление: установленный UI и конечная проверка

Срез 2026-10-10T00:40:06.833372+00:00. **UI639b6ad5 / API369654a0** на3015 и существующем публичном адресе.
[Неизменяемый receipt](CONTINUOUS-AUTO-RECOVERY-INSTALLED.json) ·
[Контракт, отрицательные срезы и регрессии](CONTINUOUS-POINTER-RECOVERY.md).

Установлен exact-source production artifact из hosted Frontend CI38009290896.
Источник, run/attempt, SHA архива и независимая OCI identity из CI log сверены.
Installer проверил runtime identity и сохранил45соседних контейнеров/API, OTA,
маршруты и APK. Схема не мигрировалась; APKPH0111.2.49-dev/10249. Local1996tests/
142suites проверены на функциональном UI13. Финальный source639 прошёл hosted1996
frontend tests; локально84notice/pointer регрессии и types/scoped lint.28docregressions
прошли. Статусы остальных CI
сохранены в JSON именно на момент среза; установка API/APK из них не выполнялась.

## Что изменилось

Повторное idle восстановление не ограничено одной попыткой; backoff750→15000мс,
fresh native readiness обязательна. Неопределённый жест не повторяется: новый
ввод после pointer loss требует точного RELEASE3, нового viewer/кадра и STARTUP0.
Missing/foreign/unknown release и unknown HTTP не заменяются таймером успеха.
Read-only/recording/inspection/task/focus locks сохраняют границы ввода.

Подтверждённая системная кнопка во время capability negotiation теперь снимает
метку завершённого probe даже до создания controller. Capture mismatch остаётся
PROBING с ограниченным deadline, вместо бессрочного IDLE. Прежний UI344 реально
остался IDLE при101нарисованном кадре; отрицательный результат сохранён в аудите.

## Что действительно проверено

Один PH011, оба адреса: собственные кадры, native readiness, доступность нового
управления и подтверждённая навигация проверены через видимый UI. JSON содержит
timestamps/diagnostic counters/statuses каждого конечного наблюдения. Наши вкладки
закрыты; public map/протокол и API не заменены. Это конечная проверка установки.

На UI13 после первого drag появился unknown-pointer notice; автоматически вернулись
новый ready/native ACK и подтверждённый Home, без ручной кнопки. Это конечное
наблюдение восстановления, без независимого wire trace точного RELEASE. Остальные
hold/terminal/foreign/missing release/fresh-owner permutations покрыты fixtures.
На финальном UI639 эпизод повторился:00:39:00UTC notice, READY/native ACK483мс,
ручных кнопок0; новая явная команда Home подтверждена700мс, READY в00:39:13UTC,
122decoded/drawn, errors0. Notice читабелен в публичной светлой теме поверх видео;
результат прежнего жеста остаётся UNKNOWN. Public Home до этого подтверждён1182мс.
На3015 финальный UI639 получил READY/native ACK253мс и подтверждённый Home674мс;
41decoded/drawn, errors0 в срезе00:39:55UTC. Тёмная тема проверена без изменения
настроек. Эти последовательные срезы не являются синхронным latency trace.
Готовность нового owner не подтверждает результат предыдущего жеста.500мс ACK deadline сохранён; задержка
и её причина не исправлены этой UI коррекцией. Прямого канала/RTT нет, probeoff;
host-only native canary8447 остаётся отрицательным. StableAPK1.3 NO-GO.

Product9accepted/41open и legacy7 не закрываются. [WORK-STATUS](../../operations/WORK-STATUS.md)
остаётся основным списком. [Непрерывность observer](STORAGE-OBSERVER-RESUME.md):
старый процесс отсутствовал, есть разрыв; новый limited collector работает без
whole-PC writer attribution. Объём Docker VHDX не изменился в86старых samples,
хотя C: потерял6,075GiB; источник этого расхода ещё UNKNOWN.
