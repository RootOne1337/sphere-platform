# Ревью концепций интерфейса Sphere

**Дата исследования:** 28 сентября 2026 г.

**Статус:** исследовательские макеты и локально интегрированный первый срез; deployment не выполнялся.

**Основной референс:** AdminCN Free.
**Состав:** Dashboard и реестр устройств в трёх разных моделях интерфейса.

## Открыть демонстрацию

В браузере Codex откройте [сравнение трёх концепций](http://127.0.0.1:4177/sphere/concepts). Выбор варианта и переключатель «Операционный обзор / Реестр устройств» сохраняют состояние в URL.

- [Fleet Console — обзор](http://127.0.0.1:4177/sphere/concepts?concept=admincn&view=dashboard) · [реестр](http://127.0.0.1:4177/sphere/concepts?concept=admincn&view=devices)
- [Signal Room — обзор](http://127.0.0.1:4177/sphere/concepts?concept=signal&view=dashboard) · [реестр](http://127.0.0.1:4177/sphere/concepts?concept=signal&view=devices)
- [Fleet Atlas — обзор](http://127.0.0.1:4177/sphere/concepts?concept=atlas&view=dashboard) · [реестр](http://127.0.0.1:4177/sphere/concepts?concept=atlas&view=devices&worker=worker-03)

Это production-сборка из отдельной копии AdminCN в `.local-pilot/admincn-research`; её зависимости и маршруты изолированы от Sphere. Макет использует **24 синтетические записи** и явно маркирован как preview. Он не вызывает API, WebSocket, OTA, stream, Android-команды, не удаляет устройства и не изменяет данные. Поиск, статусные фильтры, переход между экранами, выбор worker и локальный инспектор работают только на fixture. Недоступные в макете действия помечены, а не выдают фиктивный успех.

## Три варианта

| Вариант | Как устроен экран | Где полезен | Ограничение |
|---|---|---|---|
| **Fleet Console** | Компактная боковая навигация AdminCN; сводка состояний, очередь внимания, события и знакомая таблица. | Универсальная стартовая страница и частые операции оператора. Самый короткий путь от референса к будущей интеграции. | Общая сводка не объясняет, на каком worker сконцентрирована проблема. |
| **Signal Room** | Сначала распределение сигналов и свежие события, рядом список требующих внимания устройств; в реестре — triage-фильтры и инспектор. | Разбор `connecting/offline/error`, диагностика heartbeat и переход от события к конкретному устройству. | Требует хорошего backend event-контракта и ясных правил приоритета. Макет не утверждает, что его вымышленные события — реальные сигналы Sphere. |
| **Fleet Atlas** | Иерархия `worker → устройства`, сводка доступности узла, затем карточка выбранного устройства. | Когда у оператора одновременно несколько удалённых станций и нужно различать инстанс/хост, а не только весь парк. | Сейчас `server_name` — доступное поле устройства, но это само по себе не доказательство стабильного идентификатора физического worker. В макете группировка синтетическая; в продукте её нельзя считать реальной без подтверждённого контракта. |

### Рекомендация к обсуждению

Для первого продуктового шага лучше сохранить спокойный shell и реестр Fleet Console как основу, взять у Signal Room приоритетную очередь событий и переход «сигнал → устройство», а Atlas рассматривать как дополнительную группировку после подтверждения backend-поля worker identity. Это не готовое решение для слияния: три варианта оставлены рядом, чтобы сначала выбрать информационную архитектуру.

Системы наблюдаемости подкрепляют такой подход: Grafana связывает повторно используемые dashboard-фильтры с URL и drill-down; Sentry ставит issue-feed и triage в начало расследования; Railway показывает сборные, фильтруемые структурированные логи между сервисами; Linear демонстрирует отдельную интерактивную рабочую среду. Из этих продуктов не копировались исходники или изображения — изучались опубликованные демо и документация.

## Скриншоты из браузера

Все изображения сняты из реально запущенной production-сборки макета на `4177`, а не сгенерированы как иллюстрации. Desktop размеры проверены при CSS viewport 1920×1080, 1440×900 и 1366×768.

### Fleet Console / AdminCN

Скриншоты исходного первого варианта: [Dashboard 1920×1080](screenshots/sphere-admincn-dashboard-1920x1080.png) · [1440×900](screenshots/sphere-admincn-dashboard-1440x900.png) · [1366×768](screenshots/sphere-admincn-dashboard-1366x768.png).
Реестр: [1920×1080](screenshots/sphere-admincn-devices-1920x1080.png) · [1440×900](screenshots/sphere-admincn-devices-1440x900.png) · [1366×768](screenshots/sphere-admincn-devices-1366x768.png).

### Signal Room

Dashboard 1440×900:

![Signal Room dashboard](screenshots/signal-dashboard-1440x900.png)

Реестр 1440×900:

![Signal Room device triage](screenshots/signal-devices-1440x900.png)

Другие размеры: [Dashboard 1920×1080](screenshots/signal-dashboard-1920x1080.png) · [1366×768](screenshots/signal-dashboard-1366x768.png) · [реестр 1920×1080](screenshots/signal-devices-1920x1080.png) · [1366×768](screenshots/signal-devices-1366x768.png).

### Fleet Atlas

Dashboard 1440×900:

![Fleet Atlas worker overview](screenshots/atlas-dashboard-1440x900.png)

Реестр 1440×900:

![Fleet Atlas worker registry](screenshots/atlas-devices-1440x900.png)

Другие размеры: [Dashboard 1920×1080](screenshots/atlas-dashboard-1920x1080.png) · [1366×768](screenshots/atlas-dashboard-1366x768.png) · [реестр 1920×1080](screenshots/atlas-devices-1920x1080.png) · [1366×768](screenshots/atlas-devices-1366x768.png).

## Что можно перенести, не меняя бизнес-логику

В основной Sphere frontend сейчас используются Next.js `15.5.26`, React 19, Tailwind CSS 3, Radix UI, TanStack Query и TanStack Table. Исследованный AdminCN использует Next.js 16, Tailwind 4 и Base UI. Поэтому целиком переносить проект или обновлять стек ради внешнего вида не следует: это смешало бы независимые изменения интерфейса и платформы.

Безопасная граница будущей интеграции — перенести и проверить по одному слою:

1. Визуальные токены: нейтральные поверхности, типографическую шкалу, отступы, границы, фокус и цвета статусов — в текущие CSS variables/Tailwind 3.
2. Компоновку: ритм заголовка, sidebar, рабочую ширину, карточки состояния, responsive table container и локальную панель инспектора — на текущих компонентах и Radix primitives.
3. Представление данных: адаптировать действующий `Device` из `frontend/lib/hooks/useDevices.ts`; оставить `useDevices`, React Query, текущую авторизацию, обработку ошибок, серверную пагинацию и mutation hooks источником поведения.
4. Действия: привязывать stream, screenshot, logcat, команды, delete и OTA только к существующим авторизованным операциям и подтверждать каждый результат реальным API-ответом. В этом preview все такие действия отключены.

Текущий контракт `Device` включает `id`, `name`, Android/model/version, agent version, status, tags/groups, `server_name`, heartbeat/last-seen/connected timestamps, battery/CPU/RAM/screen, ADB и VPN поля. В нём нет авторитетных `FPS`, возраста последнего видеокадра, bitrate, transport RTT или надёжного вычисленного uptime. Такие показатели нельзя рисовать в рабочем dashboard, пока телеметрия/API не определит единицы измерения, источник, freshness и поведение при `null`.

## Проверки и найденные проблемы в бесплатном шаблоне

Для изолированной копии выполнены `pnpm check-types`, `pnpm lint`, optimized production `pnpm build` и браузерная проверка шести экранов (три концепции × два режима). На ширине 390 px у всех шести экранов `documentElement.scrollWidth = innerWidth`; горизонтального переполнения документа нет. Проверены поиск Signal Room, статусное сужение списка, открытие/закрытие инспектора, выбор worker в Atlas, прямой URL с `worker=worker-03` и отсутствие новых console errors после исправления.

Во время мобильной проверки нашлась ошибка самого исходного AdminCN hook: `useIsMobile()` читал `window.innerWidth` при первом клиентском render, а сервер рендерил `false`; на мобильном это вызывало React hydration error #418. В локальной исследовательской копии начальное состояние сделано детерминированным, а фактическая ширина применяется в `useEffect`. Production build пересобран, затем повторены все шесть мобильных маршрутов. Исправление находится только в `.local-pilot/admincn-research/src/hooks/use-mobile.ts`; основной frontend не менялся.

## Лицензии и авторство

- **AdminCN Free:** исходник закреплён на `dd1afd2f3a794ea9e746197de314f81d43670ea1`. В repository `LICENSE.md` указан MIT, Copyright © 2026 shadcn/studio; README просит атрибуцию. В прототипе оставлены авторство и ссылки на source/license. Полный текст проверенного MIT notice сохранён в [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
- У отдельной [страницы общих условий Shadcn Studio](https://shadcnstudio.com/license) есть дополнительные положения о запрете перепродажи/перераспределения и конкурирующих продуктах, которых нет в checkout MIT-файла. Это расхождение нельзя считать юридически разрешённым только потому, что GitHub repo говорит MIT. Перед включением заметного количества AdminCN-кода в публичный или коммерческий Sphere следует получить письменное разъяснение правообладателя и сохранить применимый notice.
- **Studio Admin:** исходник `3502692575348c01512d5c496648e9a948769bd6`, MIT, Copyright © 2024 Mohammed Arham Khan. Репозиторий и demo изучены как вторичный референс; его исходники и assets не копировались.
- Grafana, Sentry, Railway и Linear использованы как продуктовые референсы/демонстрации; их source code/assets в макет не добавлялись.

## Источники

**Референсы и лицензии**

- [AdminCN Free source](https://github.com/shadcnstudio/shadcn-nextjs-admincn-admin-template-free) · [repository MIT license](https://github.com/shadcnstudio/shadcn-nextjs-admincn-admin-template-free/blob/main/LICENSE.md) · [официальная страница](https://shadcnstudio.com/templates/admin-dashboard/admincn-free) · [рабочее demo](https://shadcn-nextjs-admincn-admin-template-free.vercel.app/dashboard/orders) · [общие условия Shadcn Studio](https://shadcnstudio.com/license).
- [Studio Admin source](https://github.com/arhamkhnz/next-shadcn-admin-dashboard) · [MIT license](https://github.com/arhamkhnz/next-shadcn-admin-dashboard/blob/main/LICENSE) · [рабочее demo](https://studio-admin.arhamkhnz.com/).

**Операционные интерфейсы**

- [Linear interactive demo guide](https://linear.app/docs/start-guide) (демо сохраняет изменения локально в браузере и сбрасывается при перезагрузке).
- [Sentry Sandbox](https://sandbox.sentry.io/) · [Grafana Play dashboards](https://play.grafana.org/dashboards/f/examples/examples) · [Grafana dashboard variables](https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/).
- [Railway observability logs](https://docs.railway.com/observability/logs) · [Railway CLI logs and filters](https://docs.railway.com/cli/logs).

## Статус интеграции в Sphere — 28 сентября 2026

Начат первый локальный вертикальный срез в существующем frontend. Это уже не только три статичных концепта, но интеграция пока не опубликована и не развернута.

- Dashboard получает сводку устройств из `/devices/status/fleet`, состояние сервиса из `/health`, состояние VPN из `/vpn/pool/stats` и `/vpn/health`, а последние события — из существующего журнала событий. Запросы выполняются через текущий API-клиент и TanStack Query; карточки имеют состояния загрузки, ошибки, пустых данных и устаревшего снимка. Неавторитетные FPS, задержки кадров и скорость видео не показываются.
- В реестре устройств быстрые карточки статусов действуют как реальные фильтры текущей выборки. Фильтры учитывают поиск, группу и локацию; прежние операции выбора и массовых действий остаются на существующих компонентах, мутациях и подтверждении удаления.
- Навигация сгруппирована по рабочим областям, локализована и сохраняет все 22 прежних маршрута. Проверены активный маршрут, сворачивание, мобильное закрытие меню и выход из аккаунта.
- Макеты AdminCN и Studio Admin остаются исследовательскими прототипами с демонстрационными данными. В рабочий frontend переносились идеи компоновки и визуального ритма; исходники и assets AdminCN/Studio Admin не копировались. Указанные выше лицензионные заметки по-прежнему относятся к исследовательским материалам.

Реализация находится в [Dashboard](/frontend/app/%28dashboard%29/dashboard/page.tsx), [реестре устройств](/frontend/app/%28dashboard%29/devices/page.tsx), [фильтрах устройств](/frontend/src/features/devices/deviceListFilters.ts) и [навигации](/frontend/src/features/navigation/NOCSidebar.tsx). Источники данных и бизнес-операции остаются существующими контрактами проекта.

### Проверки этого среза

- `npm run type-check` — успешно.
- `npm test -- --runInBand` — 45 наборов, 316 тестов; включая проверку переходов статуса в реестре, Dashboard API-состояний, прежних bulk-delete компонентов и logout — успешно.
- `npm run build` на Windows и сборка Docker-образа на Linux с Next.js 15.5.26 — завершились успешно; оптимизированные маршруты включают Dashboard и реестр. ESLint выводит существующие предупреждения в других файлах.
- В Windows и Linux сборка также печатает предупреждение Next о пропущенном `page_client-reference-manifest.js` при копировании standalone trace; сборка всё же завершается, образ собирается. В контейнере `/login` отвечает 200, а `/dashboard` корректно уводит неавторизованного пользователя на `/login`. Изолированный образ запускался без same-origin backend proxy, поэтому его `auth/refresh` получил 404; это не проверка production proxy или авторизованной работы.
- Локальный API health endpoint ответил 200. Во время этой работы не выполнялись удаление устройств, другие изменяющие API-запросы или deployment.

### Что остаётся подтвердить

Нужен авторизованный браузерный просмотр Dashboard и реестра на реальных данных: проверить отображение реального числа устройств, переходы фильтров, доступность массовых операций и отсутствие регрессий на существующих экранах. Из текущей среды браузер не получил авторизованную сессию, поэтому этот этап не отмечается как пройденный. Также требуется разобрать предупреждение Next standalone trace и повторно проверить production image/runtime перед публикацией. Никакие результаты живой работы APK, stream, OTA или backend mutation этим UI-срезом не заявляются.

Следующий этап — авторизованная визуальная QA на local preview, затем по одному переносить выбранные визуальные решения на нужные экраны, сохраняя существующие API и проверяя каждую реальную операцию. Только после этого можно оценивать готовность к deployment. Полную замену frontend или миграцию на стек шаблона эта работа не предлагает.
