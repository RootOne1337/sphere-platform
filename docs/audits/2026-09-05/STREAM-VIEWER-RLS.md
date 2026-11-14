# Вход в просмотр с ограниченной PostgreSQL ролью

**13 сентября 2026 · AUD-110 · High operational · настоящий PostgreSQL с RLS.**

## Дефект и доказательство

WebSocket `/ws/stream/{device_id}` проверял подпись JWT, затем читал `users`,
не установив контекст организации для Row Level Security. При штатной роли
`NOBYPASSRLS`, которая не владеет таблицами, корректный пользователь становился
невидимым запросу и просмотр отклонялся. Успешный HTTP login этого не исключает.

Тест создаёт временную ограниченную роль в отдельной loopback audit БД,
проверяет `row_security_active('devices')`, выпускает настоящий user JWT и
вызывает production WebSocket handler. До исправления: собственное устройство
не достигает `register_viewer` (**1 failed / 1 passed**). После: собственное
устройство допускается, чужое отклоняется до регистрации (**2 passed**).
Это отдельное воспроизведение на restricted role; оно не утверждает, что текущий
pilot запущен именно с такой ролью.

## Исправление

До SQL lookup вызывается существующий `bind_tenant_context` с организацией из
проверенного access token. UUID и тип токена валидируются; организация найденного
пользователя также сверяется явно для privileged/dev подключения. DB session
закрывается до длительного WebSocket receive loop, как и раньше.

Affected: `backend/api/ws/stream/router.py`, `_authenticate_viewer`.
Regression: `tests/production/test_stream_viewer_tenant_runtime.py`.

```sh
SPHERE_RUN_INTEGRATION=1 python -m pytest tests/production/test_stream_viewer_tenant_runtime.py -q
```

Нужны isolated loopback PostgreSQL/Redis и БД с `audit` в имени:
[контракт тестов](../../../tests/production/README.md).

## Residual risk

Разрешение просмотра не означает доставку/декодирование видеокадров. Cross-worker
video transport и reconnect проверяются отдельно; здесь проверяются реальный
SQL scope и admission, а не Android capture.
