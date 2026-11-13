# Наблюдения по выдаче, отзыву и сверке VPN

Проверка 14 ноября 2026, checkout `6c08c0e1`. Основной [отчёт](../VPN-WORKFLOW-FOLLOWUP.md).

| Контроль | Наблюдение |
| --- | --- |
| Устройство без назначения плюс устройство с активной SQL-привязкой в одном отзыве | HTTP 200, `succeeded=2`, один DELETE у имитатора |
| Имитатор удалил peer, затем потерял ответ | Peer отсутствует в имитаторе, `success=false` в bulk receipt |
| Ответ POST потерян после применения в имитаторе | HTTP 503. SQL readback возвращает `provisioning` |
| SQL readback после потери ответа DELETE | `revoking` |
| Повтор назначения и отзыва для двух pending устройств | HTTP 409 для каждого, ноль вызовов провайдера |
| Цикл штатного health monitor при двух pending peers | `checked=0`, ноль вызовов провайдера |
| Чтение обоих pending peers | Нет `operation_id` и `updated_at` |
| Повтор после нормального успешного назначения | Тот же peer ID, один POST суммарно |

[Python-проба](vpn-workflow-probe.py) использовала реальный router и сервисы приложения через `ASGITransport`, SQLite в памяти, синтетического владельца организации и `MockTransport` для всех вызовов провайдера. Из корня репозитория после настройки зависимостей и обычных тестовых переменных окружения выполнить `python docs/audits/2026-11-13/evidence/vpn-workflow-probe.py` с `PYTHONPATH=.;pc-agent` для Windows. Для переменных подключения используются синтетические loopback-адреса, а ASGI lifespan не запускался.

[Jest-проба](vpn-revoke-devices.test.cjs) рендерит реальную страницу `/devices` и её диалог с подменой сетевых хуков, выбора устройств и callback уведомлений. Оба теста прошли. Страница вызвала «VPN отозван у 2 устройств» для успешной квитанции и «Не отозван VPN у 1 из 1 устройств» для неизвестного исхода, при котором кнопка отзыва вновь доступна. Команда из `frontend` в PowerShell:

```powershell
$env:NODE_PATH = (Resolve-Path -LiteralPath node_modules).Path
node_modules/.bin/jest.cmd --runInBand --no-cache --roots . ../docs/audits/2026-11-13/evidence --modulePathIgnorePatterns '\.next' --testMatch '**/vpn-revoke-devices.test.cjs' --runTestsByPath ../docs/audits/2026-11-13/evidence/vpn-revoke-devices.test.cjs
```

Штатная выборка `python -m pytest -q -p no:cacheprovider --disable-warnings tests/vpn/test_vpn_api.py tests/vpn/test_vpn_health_loop.py` дала `29 passed, 1 warning`. Набор не включает `tests/production`.
