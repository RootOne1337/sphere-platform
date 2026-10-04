# AUD-96: после смены tunnel URL требовалась ручная публикация discovery

**Severity: High · operational availability · 12 сентября 2026.**

## Baseline и root cause

На `09c5002` APK уже умел читать подписанный документ и менять management routes,
но publisher отсутствовал. Offline signer не наблюдает Docker и не публикует в
GitHub. В предыдущих native migration drills оператор отдельно подписывал новые
versions и выполнял git commit/push. При настоящем автоматическом restart connector
этого действия не происходило: APK мог бесконечно получать старый адрес.

`scripts/sync-tunnel-url.sh` не решает эту задачу: он использует фиксированные имена
старой установки, меняет `.env`/legacy JSON и перезапускает backend. Его применение
к новому пилоту затронуло бы другой стек. Он не подключался к новой установке.

## Реализация

- [Scoped publisher](../../../scripts/discovery_publisher.py): выбрать connector по
  project/service, принять URL текущего process start, проверить HTTPS installation
  и readiness, подписать следующий version, выполнить GitHub SHA CAS и local mirror.
- [Windows installer](../../../scripts/Install-DiscoveryPublisher.ps1) и
  [one-shot runner](../../../scripts/Invoke-DiscoveryPublisher.ps1): задача текущего
  пользователя при logon и каждую минуту, hidden/limited, без task password.
- Pending/committed journal, process/thread lock, read-back после PUT и повторная
  синхронизация mirror после сбоя. Неизменные routes не создают GitHub commits.
- Renewal за 7 дней до expiry, новый документ на 30 дней; прежние credentials и
  подпись APK не меняются. Signing key не помещается в public gateway.

## Regression evidence

[29 publisher tests](../../../tests/test_discovery_publisher.py) вместе с 21 signer
case: **50 passed**. Проверены request/response loss, mirror/journal disk failure,
конфликт CAS/version, rollback, renewal, source restart/cache, чужая installation,
32 competing attempts и настоящая межпроцессная OS lock.

При реализации отдельно воспроизведены и исправлены stale/expired pending cases:
до fix **2 failures**. Если route или срок изменились после неудачной публикации,
нельзя повторить старый непроверенный маршрут или просроченный документ. Теперь
они замещаются только большей version. При неизменном candidate retry использует
те же подписанные bytes и прежний version.

Windows concurrency case выявил sharing conflict: `Path.resolve` открывал live
journal до блокировки и мог мешать atomic rename другого writer. Этот лишний
filesystem read исключён, локальная thread lock дополняет OS lock.

## Runtime evidence

Действующая задача — `Sphere-Publisher-pilot-20260911`; one-shot execution успешно
завершается, status.json содержит свежие проверки. Тестовый restart ограничен
проверенным ID `sphere-pilot-20260911-cloudflare-quick-1`. Version 7 → 8 и mirror
обновлены scheduler без ручного config write или вызова publisher из теста.
Время до наблюдения publication — **39.97 s** от начала fault injection.
APK затем приняла signed v8 и выполнила настоящий echo за **250.83 s** от начала
fault injection, с тем же PID/device ID и 0 регистраций. Ручного reconnect не было.
Последующие scheduler cycles: unchanged v8, без лишних commits.
[JSON evidence](evidence/automatic-discovery-publication-20260912.json).

Отдельная проверка PostgreSQL: при pause только БД нового стенда реальная задача
завершилась с `ReadTimeout`, сохранив прежние signed mirror/journal и время последнего
успеха. После unpause следующий scheduled cycle вернулся к unchanged v8; APK
выполнила echo с тем же PID, identity и cache, без новой регистрации.
БД восстановлена в `finally`, все девять сервисов снова healthy.
[PostgreSQL evidence](evidence/publisher-postgres-failure-20260912.json).

Полный CI реализации `b76d225`: **1576 backend tests passed**, Android, frontend,
lint/security/RLS, migrations и production image bootstrap — success;
draft preview пропущен. [Архив проверок этой ревизии](evidence/ci-b76d225-summary.json).

## Residual risk

Автопубликация не гарантирует быстрый rollout GitHub Raw: [AUD-95](DISCOVERY-CDN-FRESHNESS.md)
остаётся OPEN. Нужны заранее известный альтернативный ingress и независимый свежий
config host. При смене temporary URL baked gateway mirror старой APK тоже теряет
адрес; стабильный GitHub source продолжает работать, но новый mirror host не
добавляется автоматически в root bootstrap list APK.

Задача работает при входе пользователя в Windows, с доступным Docker Desktop и
GitHub credential этого пользователя. Host reboot/pre-logon acceptance, глобальная
система alerts и отдельная Linux service installation не выполнены. Файл status
надо проверять вместе с возрастом; старый ok не означает действующий scheduler.
Другие publisher hosts с отдельными journals требуют единого владельца записи.

[Полный contract, настройка и диагностика](../../operations/DISCOVERY-PUBLISHER.md).
