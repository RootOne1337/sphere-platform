# Проверка упакованного frontend перед установкой

Дата: **6 октября2026, UTC**. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Статус: source fix / новый hosted probe ещё должен исполниться.

## Доказательство пробела

Frontend [run37511486748, source517d73b](https://github.com/RootOne1337/sphere-platform/actions/runs/37511486748)
успешно выполнил **1686 tests /133 suites**, TypeScript, Next production build
и `test -f .next/standalone/server.js`. При сборке в18:30:50Z Next сообщил
ENOENT при копировании `app/(dashboard)/page_client-reference-manifest.js`.
Exit0 и наличие server.js не доказывали, что страницы/JS/CSS доступны из artifact.

В исходниках были два redirect page для `/`: `app/page.tsx` и
`app/(dashboard)/page.tsx`. Оба направляли на `/dashboard`; route group не
создаёт дополнительный URL. Дублирующая group page удалена, единственный root
redirect сохранён. Связь этого изменения с устранением warning должна быть
проверена следующим build, не предполагается по source alone.

## Что изменено

- CI после production build копирует public и .next/static в standalone так же,
  как runner [Dockerfile](../../../frontend/Dockerfile).
- [Probe](../../../tests/containers/frontend_standalone_probe.mjs) запускает
  **standalone/server.js** на ephemeral127.0.0.1 port. Не next dev/next start.
- Из packaged app-paths manifest извлекаются все concrete page routes;
  route groups удаляются, URL deduplicated. Dynamic templates, API handlers и
  internal not-found не выдаются за полноценно проверенные user routes.
- Наличие root/login/scripts/builder/devices/monitoring обязательно. Root должен
  вернуть307/308 на/dashboard; остальные страницы —200HTML с client JS.
- Все advertised `/_next/static/` assets загружаются без redirect.404, пустой
  ответ, HTML вместо chunk, неверный JS/CSS MIME или500 provokes failure.
- Страницы ограничены2MiB, asset16MiB,512manifest entries/assets; запрос10s,
  startup ограничен. Собственный child останавливается в finally, чужие процессы
  не ищутся и не останавливаются. Logs capped16KiB, response bodies не печатаются.
- [10 HTTP regression cases](../../../tests/containers/test_frontend_standalone_probe.mjs)
  проверяют ошибочные packaged responses, missing JS, SSR error с status200,
  root destination и byte budget. **Локально10/10 passed** без Next build.

Локальная стандартная type-check после удаления duplicate root остановилась
на **старом generated `.next/types/validator.ts`**, который импортирует удалённую
group page. Generated output установленной сборки не изменялся. Fresh hosted
type-check/build должен регенерировать свой manifest; этот локальный запуск
не отмечается как успешный и не является причиной возвращать duplicate route.
Отдельная source-only type-check с прежними options и explicit frontend @types,
без generated `.next`/`.next-audit`, прошла. Она не подменяет стандартную
fresh hosted type-check и проверку новых generated route types.

Проверка использует официальное поведение
[Next standalone output](https://nextjs.org/docs/app/api-reference/config/next-config-js/output):
public/static доставляются отдельно от traced server. Новые npm dependencies
не добавлены. Workflow: [ci-frontend.yml](../../../.github/workflows/ci-frontend.yml).

## Что этот receipt не доказывает

Probe выполняется на hosted runner с synthetic HTTP проверками. **Нет** browser
hydration, pointer/SVG layout, реальных auth/API/Android данных, WebSocket control,
frame latency, Docker runner UID/container isolation или capacity/load tests.
JSON явно содержит `browserHydrationVerified:false`, `backendExecutionVerified:false`.
Он усиливает admission artifact, не заменяет installed visual/runtime acceptance.

На ПК C: остаётся Warning/Full Repair Needed; локальный Next build, новый server
и deploy этой ревизии не запускались. Installed UI1c26ffc7/APIeb7a7c26 сохранены.
Реестр9/41 не изменён. Source517d73b full CI и следующий probe head фиксируются
отдельно; прежний green workflow не переносится на новый код.
