# AUD-141 — фиксированный корень standalone-сборки frontend

**23 сентября 2026 · F32-30 · P2 / Medium · исправление в коде PR19; проверка выполнения пройдена.**

[Fleet32 readiness](FLEET32-PREFLIGHT.md) · [Готовность](../../operations/READINESS.md) · [Документация frontend](../../README.md)

## Влияние и первопричина

Frontend собирается в standalone-режиме; Dockerfile копирует
`.next/standalone/server.js` в корень образа и запускает `node server.js`.
Next.js автоматически выбрал посторонний lockfile выше checkout как корень workspace.
Из-за этого успешный локальный `next build` создал `server.js` во вложенном каталоге
standalone, а ожидаемого файла в корне артефакта не было. Код возврата 0 сам по себе
не подтверждал готовность этого артефакта к Docker.

В [next.config.ts](../../../frontend/next.config.ts) корень трассировки явно привязан
к рабочему каталогу приложения. Это использует [официальную настройку трассировки
файлов Next.js](https://nextjs.org/docs/app/api-reference/config/next-config-js/output)
и не включает каталоги выше frontend-проекта.

## Воспроизведение и исправление

До изменения локальная сборка не создавала `.next/standalone/server.js` в ожидаемом
месте; файл оказывался глубже, под каталогами workspace. После `outputFileTracingRoot`
корневой `server.js` создаётся. Запущенный из standalone отдельный процесс вернул
HTTP 200 для `/`, `/dashboard`, `/devices` и `/stream`; после smoke-проверки процесс
был остановлен.

Файлы: [next.config.ts](../../../frontend/next.config.ts),
[frontend/Dockerfile](../../../frontend/Dockerfile) и уже существующая проверка
[`server.js` в CI](../../../.github/workflows/ci-frontend.yml). Сборочный workflow
проверяет тот же путь `test -f .next/standalone/server.js`.

## Проверка и остаточный риск

- `npm run build` завершился успешно; проверка наличия корневого standalone entrypoint
  прошла.
- Standalone-сервер запустился; четыре основных маршрута вернули HTTP 200.
- На Windows Next.js продолжил печатать предупреждение о неудачном копировании
  отсутствующего `page_client-reference-manifest.js` для группы маршрутов. Это отдельное
  предупреждение: проверенные маршруты работали, но полный Docker image из этого
  Windows-артефакта здесь не собирался.
- Linux frontend CI на `2cb4a9d` прошёл `npm run build` и `test -f
  .next/standalone/server.js`; frontend unit tests и type check также прошли. Отдельный
  frontend Docker-image build из этого артефакта не запускался.

Исправление не меняет существующий контейнер или pilot. Оно стабилизирует путь
локальной standalone-сборки; Linux CI подтвердил root entrypoint, тогда как Windows
trace-copy warning и frontend Docker-image validation остаются открытыми.
