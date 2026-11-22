# Адресная диагностика PH030: установленный веб и API

Срез 2026-10-10T06:36:12.043608+00:00. UI/API **c17332eb** обслуживают3015 и существующий публичный адрес.
[Неизменяемый receipt](DIRECT-ADMISSION-INSTALLED.json) ·
[Адресный OTA, сеть и предыдущие ограничения](DIRECT-PROBE-TURN-AND-LAPTOP.md).

## Установка и действительная проверка

Exact-source frontend/backend CI images сверены по GitHub archive digest,
независимой image identity, source/run/attempt и упакованному runtime. Backend
обновлён с369654a0, веб с639b6ad5. Каждый installer сохранил45соседних контейнеров,
каталог OTA и схему. SQL migration/seed и публичная host map не изменялись.

Диагностический allowlist содержит только PH030. На обоих адресах: anonymous401,
authenticated200, private/no-store, два профиля и фиксированные30секунд/20замеров.
PH011 получает enabledfalse/profiles[]. HTTP read не создаёт peer и TURN credential.
Панель визуально открыта на двух адресах; старт проверки не нажат.

PH030 ранее получил1.2.50-dev/10250 адресным OTA: установленный SHA подтверждён
отдельным receipt. Новая установка веба/API APK не меняла. Актуальный статус
доступности и last heartbeat записаны в HTTP observations; факт установки APK
не доказывает постоянную связь или успешный прямой канал.

## Проверки и границы

Frontend CI:2106tests/146suites, types/build и packaged26pages/73assets. Локально
437stream/grid regressions,87focused backend,27installer и29documentation tests
прошли. Backend CI:3492passed/252subtests/37skipped. Остальные CI статусы сохранены
на дату среза, а не перенесены между SHA.

Это **установленный echo-only диагностический pilot**, не прямые видео и ввод.
TURN не настроен на публичном узле. Channel/RTT именно браузера ноутбука,
global/LAN matrix, native relay, ownership, input-to-picture latency и soak OPEN.
StableAPK1.3.0 не объявлен. Product9/41 и legacy7 остаются прежними.

Срез observer включён в JSON отдельно: нет полной атрибуции writer C:;
постоянный Docker VHDX в измеренном окне не объясняет весь расход диска.
