# Broadcast: установленное исправление и конечная приёмка

Дата: 10 октября 2026 UTC+5; runtime timestamps ниже — UTC 9 октября.
Статус: **INSTALLED_FINITE** для двух доказанных причин HTTP 500.
Полный продукт, stream reliability и direct transport этим не приняты.

## Результат

UI и API `369654a0be4bded35e299062badc9bfe95101f1e` установлены на 3015 и выбранном
публичном Tuna-host. Presence MessagePack читает бинарный Redis-клиент; обязательный
online_devices передаётся при создании ответа уже сохранённого батча.
[Исходное доказательство](BROADCAST-BINARY-PRESENCE.md) остаётся историческим source receipt.

В изолированном PostgreSQL/Redis regression подтверждены HTTP 202, durable plan,
org/version/targets и ровно одно задание после admission worker. Дополнительные
focused tests проверяют исключение foreign/busy/offline/inactive/corrupt presence.
На рабочем стенде выполнена проверка ошибки с заранее проверенным отсутствующим
script UUID: оба адреса вернули 404 `Script not found` после реального чтения
presence. Массовые задания и Android-команды не отправлялись.
Это разные проверки: live 404 не выдаётся за live execution или runtime 202.

## Доставка

| Слой | CI run | Artifact | Запуск контейнера UTC |
|---|---|---|---|
| UI | 37993531687 | 11645858028 | 21:35:07.521123551 |
| API | 37993531649 | 11645718243 | 21:46:27.920139598 |

При каждой установке проверены archive/source/independent CI identity, допустимый
source delta, полный Compose baseline, отсутствие resource findings и сохранение
45 других контейнеров. Сначала отдельно заменён UI, затем отдельно API. Docker
build/prune, SQL migration, APK reinstall и OTA publish не выполнялись.
Schema head: `20261006_script_catalog_metadata`.
OTA SHA-256: `5d5dcb5521277b51f366ea5370a2f7df5fd62696de0d5b7b86a56b443b03af10`.
Direct endpoint выключен, allowlist пуст; unauthenticated probe получил4003
`direct_probe_disabled`. PH011 после API replacement снова online.

CI archive identity и Docker loaded identity записаны отдельно в
[машинном receipt](BROADCAST-INSTALLED-ACCEPTANCE.json). Containerd преобразует
manifest при load; installer проверяет соответствие archive/config/manifest,
а не объявляет разные image IDs побайтово одинаковыми.

## Проверки

- Все четыре exact-source CI завершились success: Backend, Frontend, Android,
  Preview. Backend: **3428 passed,37 skipped,252 subtests**, coverage80.94%.
- Full Ruff/mypy, security/RLS, Alembic single head, generated HTTP documentation
  и отдельный Redis container memory/persistence probe прошли.
- Frontend: **1966 tests /142 suites**, types/build; standalone image probe:
  26 pages /73 client assets. Android source не менялся относительно прежнего
  API rollout; successful Android CI не означает установленную новую APK.
- Local: health200, build369, broadcast missing-script404 за12.16мс.
  Public: health200, build369, тот же404 за245.22мс. Две точки — не SLA/p95.
- В bounded backend log tail за окно запросов unhandled broadcast errors:0.
- Конечная браузерная проверка каталога, существующего graph и формы запуска
  записана в JSON. Рабочий сценарий, версии, граф и задания не изменялись.

## CSS preload

Исходный chunk `599369d853c61df7.css` до установки имел одинаковые байты/HTTP200
на обоих адресах. `as="style"` подтверждён. Предупреждение не воспроизвелось в
ограниченной навигации каталог → builder → каталог; причиной route prefetch его
называть нельзя без дополнительного trace. Новая установка проверяется отдельно,
без отключения Next preload и без сокрытия console warnings.

## Что остаётся открытым

1. Broadcast idempotency и reconciliation при потере HTTP ответа после commit;
   unknown Redis state, >1000 targets, expected-version UI и точность success toast.
2. Idle native_receipt_timeout. На новом UI / прежнем API публичный viewer опять
   остановился на heartbeat512мс. Последний ACK487мс против244мс локально:
   [последовательное сравнение и пределы вывода](IDLE-LOCAL-PUBLIC-COMPARISON.md).
   Этот API delta не является исправлением transport latency. Deadline/replay
   не менялись; unknown terminal input не повторяется.
3. Direct close-race/phase/network diagnostics доставлены в source369, но новый
   native ICE canary, live RTT, STUN/TURN, media/input и network/resource matrix
   не приняты. Probe по-прежнему отключён.
4. Whole-PC writer неизвестен; limited observer возобновлён отдельно. Удалены
   только собственные duplicate download ZIP и неустановленный старый archive:
   829695529B. Актуальные архивы/rollback images сохранены. Это не устранение утечки.
5. Product9accepted/41open и legacy7 не изменились. APK1.3.0 пока NO-GO.

[Текущий реестр](../../operations/WORK-STATUS.md) ·
[Source / installed / finite acceptance](../../DOCUMENTATION.md).
