# Проверка упакованного frontend перед установкой

Дата: **6 октября2026, UTC**. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Статус: **hosted frontend source accepted наe7f3ffb; installed/browser/runtime open**.

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
  подтвердить redirect на/dashboard:307/308 с same-origin Location либо200HTML
  с точным Next meta/RSC redirect payload. Простого200 недостаточно; остальные
  страницы —200HTML с client JS.
- Все advertised `/_next/static/` assets загружаются без redirect.404, пустой
  ответ, HTML вместо chunk, неверный JS/CSS MIME или500 provokes failure.
- Страницы ограничены2MiB, asset16MiB,512manifest entries/assets; запрос10s,
  startup ограничен. Собственный child останавливается в finally, чужие процессы
  не ищутся и не останавливаются. Logs capped16KiB, response bodies не печатаются.
- [10 HTTP regression cases](../../../tests/containers/test_frontend_standalone_probe.mjs)
  проверяют ошибочные packaged responses, missing JS, SSR error с status200,
  root destination и byte budget. Первый набор10/10; после уточнения Next
  redirect semantics **локально18/18 passed** без Next build.

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

## Первый hosted probe и корректировка его ожидания

Head44af412, [run37513667851](https://github.com/RootOne1337/sphere-platform/actions/runs/37513667851):
1686/133 tests, стандартные fresh types и production build success; прежний
missing root manifest warning в этом build больше не появился. Packaged server
запустился127.0.0.1 и Ready191ms. Probe упал: **Root did not redirect:200**.
Это неверное требование самого probe, а не подтверждение сломанного root.

Проверены [официальные redirect semantics](https://nextjs.org/docs/app/api-reference/functions/redirect)
и установленный Next15.5.26 server-inserted-html source: streamed redirect может
быть meta в200HTML. Исторический generated index.html также содержит типизированный
Flight error digest `NEXT_REDIRECT;replace;/dashboard;307;`.
Probe теперь распознаёт только framework meta с expected id/refresh/internal URL
или JSON-parsed self.__next_f error payload с exact destination/status. JavaScript
не исполняется. HTTP redirect на другой origin, пустой200, fake/plain token,
неверный RSC destination/status и external meta rejected. Receipt пишет фактический
redirect kind; это не browser hydration proof. Assets staged contents-to-contents,
чтобы существующая target directory не превращала public/static в nested copy.
18 local cases прошли; последующий exact-head hosted result указан ниже.

## Принятый hosted artifact receipt

Head **e7f3ffbe547e7cf81b1b33feb9a10bd9d3ceeb31**,
[run37514629812](https://github.com/RootOne1337/sphere-platform/actions/runs/37514629812),
6 октября18:54:29Z: **success**.1686frontend tests /133 suites,18 HTTP contract
cases, стандартные fresh types, Next build и standalone probe passed.
Missing traced root manifest warning count0. **26 concrete pages /73 client assets**
проверены; root200 признан по typed Next Flight redirect на/dashboard.
[Machine-readable receipt](FRONTEND-STANDALONE-EVIDENCE.json).

Никакой installed UI/API/APK этим результатом не обновлён. Browser hydration,
layout, real data/actions, dynamic detail routes и Android execution не проверены.
Backend/Android этого нового head ещё выполнялись в момент frontend receipt;
их последний полный source receipt517d73b указан отдельно. После документационного
коммита новый HEAD не называется этим же выполненным кодом без ссылки на exact SHA.
