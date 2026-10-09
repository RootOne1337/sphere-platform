# 🗺️ Куда движется Sphere

**Проверенная установка:** UI `d70f55c6` / API `9ad3481c`.

**Навигация обновлена 9 октября 2026; F32-план ниже сохраняет порядок21 сентября.** [Главная](README.md) · [Реестр работ](docs/operations/WORK-STATUS.md) · [Установленный pilot](docs/operations/LOCAL-PILOT.md)

**Текущий продуктовый план:** [50 работ с зависимостями и приёмкой](docs/operations/STATUS-REGISTRY.json),
EP-001–009 приняты,41 пункт сохраняют открытые критерии.
[Последний пакет ресурсной истории](docs/audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md).
EP-009: принята история cgroup CPU/RAM; host/RSS остаются отдельными scope.
EP-010 продолжается: [tenant coverage UI/API установлен](docs/audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE.md),
[clock/ownership foundation сохранён](docs/audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION.md).
[Независимый producer, история coverage и транспортные probes](docs/audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-NEXT.md) ещё открыты. Эксплуатационный порядок пересмотрен: сначала EP-033/047 resources,
remote rollout/recovery и selected-device control, затем Studio и реестр по dependencies.
[Текущие41 работы, масштаб и дополнения из чата](docs/operations/WORK-STATUS.md).
[Ограниченный reader и persistent logs](docs/audits/2026-10-06/DEVICE-LOG-READ-BUDGET.md)
установлены частично; EP-033 целиком остаётся OPEN.
[Upload intake и writer budget](docs/audits/2026-10-06/DEVICE-LOG-UPLOAD-BUDGET.md)
первоначально установлены в API `76596c39` (исторический rollout); ресурсы следующего этапа — общие квоты, независимая
очистка, rotation/delete consistency и leak/load proof. Счёт 9 / 41 не изменён.
Планируемый пользовательский stream+script тест20–30 эмуляторов — отдельный
живой этап; целевой F32-план32 ниже не считается выполненным по 14 online.
Будущие VPN-адаптеры/AI и универсальные project databases не входят в текущую
приёмку наблюдаемости и не подменяют её.

Ближайший результат — **32 настоящих эмулятора с живыми экранами, заданиями и
восстановлением после отказов**. Этап закрывается доказательствами, а не числом
коммитов. Здесь порядок работы; подробные причины, файлы и tests — в реестре F32.

## 01 · Основа исполнения — установлена, масштаб ещё проверяется

Сохранённые stop intents, pipeline checkpoints, batch plan, RLS worker paths,
ограниченный browser decoder и согласованный Redis memory budget установлены.
Приняты перечисленные isolated/two-device сценарии.
[Canary](docs/audits/2026-09-20/CANARY-20260921.md) · [Decoder](docs/audits/2026-09-20/DECODER-RECOVERY.md) · [Redis](docs/audits/2026-09-20/REDIS-MEMORY.md).

## 02 · Видео и управление под нагрузкой — следующий приоритет

- Довести облегчённый профиль экрана через UI → backend → APK до encoder.
- Ограничивать работу до кодирования, сохранять корректную цепочку видеокадров.
- Измерить свежесть изображения и задержки команд на загруженном канале.
- Проверить несколько viewers, reconnect, rotation и перегруженный браузер.

Критерий: применённый профиль подтверждён, управление остаётся работоспособным,
после восстановления сети показываются новые кадры. **F32-06/07/08/22**.

## 03 · Наблюдаемость и восстановление — до длинного прогона

Подключить метрики реальной установки и workers, проверить backup/restore,
ротацию логов, Redis buffers/eviction, runtime DB role и recovery сложных pipelines.
Собирать timeline по времени, устройству и task/command ID. **F32-09/10/17/18/25**.

## 04 · Приёмка 4 → 8 → 16 → 32

Для каждого шага фиксировать версии, нагрузку CPU/GPU/RAM/network, latency,
новые кадры и terminal receipts. После этого — конечный смешанный soak с
отказами Android/server network, PostgreSQL, Redis и backend.

**32 и 8h пока не passed.** Тест в состоянии running не считается успехом.
[Harness и критерии](docs/operations/ANDROID-OVERNIGHT-SOAK.md) · **F32-19/22/23**.

## 05 · Смежные режимы — перед их использованием

VPN provider/routing/kill switch и end-to-end; атомарный OTA-каталог; durable
PC-agent receipts; completion webhooks; независимый ingress failover; быстрая
отмена sleep; исправление preview deployment. **F32-11–16/20/21/26/27**.
Приоритет внутри этапа зависит от того, какой режим включается в приёмку.

## 06 · Универсальные проекты и AI — позже

Отделить предметные сценарии от базовой платформы, затем проектировать подключаемые
AI consumers: свежие наблюдения, владение управлением, deadlines и воспроизводимые
действия. Текущие UI/сценарии ещё содержат предметную привязку.
[AI readiness](docs/architecture/AI-READINESS.md) — анализ, **не готовая интеграция**.

Сроки не фиксируем по количеству fixes: native нагрузка и длительные прогоны
занимают реальное время. Изменение приоритетов отражается сначала в
[Fleet32](docs/audits/2026-09-20/FLEET32-PREFLIGHT.md), затем здесь.
