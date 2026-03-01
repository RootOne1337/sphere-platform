<div align="center">

# Sphere Platform — Руководство по Web-интерфейсу

**Network Operations Center (NOC) Dashboard**

[![Next.js 15](https://img.shields.io/badge/Next.js-15-000?style=flat-square&logo=next.js)](../frontend/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react)](../frontend/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?style=flat-square&logo=typescript)](../frontend/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-3.x-06B6D4?style=flat-square&logo=tailwindcss)](../frontend/)

*Версия документа: 4.5.0 · Последнее обновление: Март 2026*

</div>

---

## Содержание

- [1. Архитектура интерфейса](#1-архитектура-интерфейса)
- [2. Авторизация и безопасность](#2-авторизация-и-безопасность)
- [3. Dashboard — Центр управления](#3-dashboard--центр-управления)
- [4. Fleet Matrix — Управление устройствами](#4-fleet-matrix--управление-устройствами)
- [5. Device Stream — H.264 стриминг](#5-device-stream--h264-стриминг)
- [6. Task Engine — Движок задач](#6-task-engine--движок-задач)
- [7. Orchestration — Визуальный DAG-редактор](#7-orchestration--визуальный-dag-редактор)
- [8. Scripts — Библиотека скриптов](#8-scripts--библиотека-скриптов)
- [9. VPN / Tunneling — Управление туннелями](#9-vpn--tunneling--управление-туннелями)
- [10. Groups — Группы устройств](#10-groups--группы-устройств)
- [11. Locations — Геолокации](#11-locations--геолокации)
- [12. Discovery — Сканер сети](#12-discovery--сканер-сети)
- [13. Users — Управление пользователями](#13-users--управление-пользователями)
- [14. Audit Log — Журнал безопасности](#14-audit-log--журнал-безопасности)
- [15. Sys Logs — Logcat просмотрщик](#15-sys-logs--logcat-просмотрщик)
- [16. Monitoring — Мониторинг инфраструктуры](#16-monitoring--мониторинг-инфраструктуры)
- [17. Updates — OTA обновления](#17-updates--ota-обновления)
- [18. Webhooks — n8n интеграция](#18-webhooks--n8n-интеграция)
- [19. Settings — Настройки пользователя](#19-settings--настройки-пользователя)
- [20. Навигация и горячие клавиши](#20-навигация-и-горячие-клавиши)
- [Приложение A — Роли и права доступа (RBAC)](#приложение-a--роли-и-права-доступа-rbac)
- [Приложение B — API эндпоинты](#приложение-b--api-эндпоинты)

---

## 1. Архитектура интерфейса

### Технологический стек

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| Фреймворк | Next.js 15 (App Router) | SSR, роутинг, middleware |
| UI-библиотека | Shadcn/ui + Radix UI | Доступные компоненты, модальные окна |
| Стилизация | Tailwind CSS 3 | Утилитарные CSS-классы |
| Состояние сервера | TanStack React Query | Кеширование, автообновление запросов |
| Локальное состояние | Zustand | Inspector, Command Palette |
| Таблицы | TanStack React Table | Виртуальный скролл, сортировка, выделение |
| Графы / DAG | React Flow (@xyflow/react) | Визуальный редактор скриптов |
| Графики | Recharts | Sparklines, Throughput |
| Терминал | @xterm/xterm | WebTerminal к устройству |
| Видеостриминг | WebCodecs API | H.264 NAL-unit декодирование |

### Структура приложения

```
frontend/
├── app/
│   ├── (auth)/login/          # Страница авторизации
│   ├── (dashboard)/           # Защищённая зона (layout с sidebar)
│   │   ├── dashboard/         # Главная панель
│   │   ├── devices/           # Fleet Matrix + Device [id]
│   │   ├── stream/            # Multi-stream + Stream [id]
│   │   ├── tasks/             # Task Engine
│   │   ├── orchestration/     # DAG Builder
│   │   ├── scripts/           # Script Library + Builder
│   │   ├── vpn/               # VPN Manager (6 вкладок)
│   │   ├── groups/            # Группы устройств
│   │   ├── locations/         # Геолокации
│   │   ├── discovery/         # Сетевой сканер
│   │   ├── users/             # Управление пользователями
│   │   ├── audit/             # Журнал безопасности
│   │   ├── logs/              # Logcat viewer
│   │   ├── monitoring/        # Метрики инфраструктуры
│   │   ├── updates/           # OTA обновления
│   │   ├── webhooks/          # n8n интеграция
│   │   └── settings/          # Профиль, MFA, API-ключи
│   └── page.tsx               # Root → redirect /dashboard
├── components/ui/             # Shadcn/ui примитивы
├── src/features/              # Доменные компоненты
├── hooks/                     # (Legacy) hooks
├── lib/hooks/                 # React Query hooks
├── lib/api.ts                 # Axios instance
└── types/                     # TypeScript интерфейсы
```

### Layout

Основной layout (`(dashboard)/layout.tsx`) включает:
- **NOCSidebar** (слева) — 17 навигационных пунктов, сворачивается до w-14 на desktop
- **Content area** (справа) — текущая страница
- **ContextInspector** (правая выдвижная панель) — детали выбранного объекта
- **GlobalCommandPalette** (оверлей `Cmd+K`) — быстрый поиск и навигация

---

## 2. Авторизация и безопасность

### Страница входа (`/login`)

| Элемент | Описание |
|---------|----------|
| **Email** | Поле ввода email-адреса, обязательное |
| **Password** | Поле пароля, обязательное |
| **Кнопка «Sign In»** | Отправляет `POST /api/v1/auth/login` |
| **MFA-экран** | Появляется, если у пользователя включено MFA — 6-значный TOTP код |

### Процесс авторизации

```
1. Пользователь вводит email + password
2. POST /api/v1/auth/login → { access_token, refresh_token }
   ИЛИ → { mfa_required: true, state_token: "..." }
3. Если MFA:
   a. UI показывает поле TOTP-кода
   b. POST /api/v1/auth/login/verify-mfa → { access_token, refresh_token }
4. Токены сохраняются в localStorage
5. Redirect → /dashboard
```

### Роли доступа

| Роль | Описание | Основные права |
|------|----------|----------------|
| `viewer` | Только просмотр | Чтение всех страниц, без модификации |
| `script_runner` | Оператор скриптов | viewer + запуск скриптов и задач |
| `device_manager` | Менеджер устройств | script_runner + CRUD устройств, групп |
| `org_admin` | Администратор организации | Полный доступ внутри организации |
| `org_owner` | Владелец организации | org_admin + управление пользователями |

---

## 3. Dashboard — Центр управления

**Маршрут:** `/dashboard`

Главная панель мониторинга — обзор всей инфраструктуры на одном экране.

### Элементы страницы

| Секция | Содержимое | Обновление |
|--------|-----------|------------|
| **Fleet Stats** | Карточки: Total Devices, Online, Offline, Issues | Автообновление 10с |
| **Device Distribution** | Круговая диаграмма по статусам | Автообновление 10с |
| **VPN Health** | Статус: Healthy/Degraded/Down + кол-во туннелей | Автообновление 10с |
| **System Metrics** | Sparkline-графики: CPU, RAM, Redis, Network | Автообновление 10с |

### Навигационные ссылки

- → **Fleet Matrix** (`/devices`)
- → **Device Stream** (`/stream`)
- → **Monitoring** (`/monitoring`)

> **Совет:** Dashboard — точка входа для быстрой оценки состояния всей платформы. Если что-то «красное», кликай на соответствующую карточку для детальной диагностики.

---

## 4. Fleet Matrix — Управление устройствами

**Маршрут:** `/devices`

Центральная таблица управления всем флотом Android-устройств. Использует виртуальный скролл TanStack для плавной работы с 200+ устройствами.

### Шапка страницы

| Элемент | Описание |
|---------|----------|
| **Заголовок «Fleet_Matrix»** | С анимированной иконкой CPU |
| **Stats Dashboard** | Inline-карточки: Total, Online (зелёный), Offline (серый), Issues (жёлтый) |
| **Поиск** | Input с иконкой `Search` — фильтрация по имени, модели, android_id |
| **Переключатель вида** | Иконки Grid/List — переключение между табличным и плиточным видом |

### Таблица FleetMatrix

**Колонки (15+):**

| Колонка | Тип | Описание |
|---------|-----|----------|
| ☑ | Checkbox | Мульти-выделение для bulk actions |
| Device Name | text | Имя устройства (кликабельное → Inspector) |
| Status | badge | `online` (зелёный) / `offline` (серый) / `busy` (жёлтый) |
| Battery | progress | Процент заряда, красный при < 20% |
| CPU | number | Процент загрузки |
| RAM | number | MB использования |
| ADB | icon | ✓ подключен / ✗ отключен |
| VPN | icon | ✓ назначен / ✗ нет |
| Group | text | Название группы (если назначена) |
| Location | text | Название локации |
| Tags | badge[] | Массив цветных меток |
| Last Seen | timestamp | Последняя активность |
| ⋯ | menu | Контекстное меню действий |

### Контекстное меню устройства (⋯)

| Действие | Диалог | Описание |
|----------|--------|----------|
| **Rename** | ✅ AlertDialog | Переименование - поле ввода нового имени |
| **Assign Group** | ✅ Dialog + Select | Выбор группы из выпадающего списка |
| **Assign Location** | ✅ Dialog + Select | Выбор локации из выпадающего списка |
| **Delete** | ✅ AlertDialog | Удаление с подтверждением (красная кнопка) |

### Bulk Actions (массовые операции)

Появляются при выделении одного или более устройств:

| Кнопка | Иконка | Описание |
|--------|--------|----------|
| **Reboot** | `RefreshCcw` | Массовая перезагрузка выбранных устройств |
| **Revoke VPN** | `ShieldOff` | Отзыв VPN для выбранных устройств |

```
Пример: Выделяешь 15 устройств → нажимаешь «Reboot» →
POST /api/v1/bulk-action { device_ids: [...15 ids], action: "reboot" }
```

### Inspector Panel (правая панель)

При клике на строку устройства открывается `ContextInspector` справа:

| Вкладка | Содержимое |
|---------|-----------|
| **Info** | Полная информация: модель, Android версия, статус, батарея, группа, VPN |
| **Scripts** | Запуск скрипта на устройстве (RunScriptTab) |
| **Terminal** | WebTerminal (xterm.js) — shell-доступ к устройству |
| **Logs** | LogcatViewer — просмотр Android logcat в реальном времени |

### Диалоги

#### Создание группы

```
┌─────────────────────────────────┐
│  Create New Group               │
│                                 │
│  Name: [________________]       │
│  Description: [_____________]   │
│  Color: [■ #3B82F6]            │
│                                 │
│         [Cancel]  [Create]      │
└─────────────────────────────────┘
```

#### Переименование устройства

```
┌─────────────────────────────────┐
│  Rename Device                  │
│                                 │
│  New name: [pixel-5-office-1__] │
│                                 │
│         [Cancel]  [Rename]      │
└─────────────────────────────────┘
```

#### Назначение группы

```
┌─────────────────────────────────┐
│  Assign to Group                │
│                                 │
│  Group: [▼ Production Fleet   ] │
│                                 │
│         [Cancel]  [Assign]      │
└─────────────────────────────────┘
```

---

## 5. Device Stream — H.264 стриминг

### Multi-Stream Grid (`/stream`)

**Маршрут:** `/stream`

Мультиэкранный просмотр видеопотоков с нескольких устройств одновременно.

| Элемент | Описание |
|---------|----------|
| **Grid Layout Selector** | Сетка: 1×1, 1×2, 2×2, 2×3, 3×3, 3×4, 4×4 |
| **Device Selector** | Выпадающие списки для каждой ячейки сетки |
| **Start/Stop** | Кнопки управления стримом в каждой ячейке |
| **Fullscreen** | Развернуть конкретную ячейку на весь экран |

### Архитектура стриминга

```
Android Device                          Browser
┌──────────────┐                 ┌──────────────────┐
│MediaProjection│                 │                  │
│      ↓       │                 │  <canvas>        │
│ MediaCodec   │    WebSocket    │      ↑           │
│ H.264 encode │ ──NAL units──→ │  WebCodecs       │
│      ↓       │   /ws/stream/  │  VideoDecoder    │
│  NAL Parser  │    {deviceId}  │      ↑           │
└──────────────┘                 │  SPS/PPS cache   │
                                 └──────────────────┘
```

### Одиночный стрим (`/stream/[id]`)

**Маршрут:** `/stream/{device-id}`

- Canvas-элемент с декодированным H.264 видео
- Заголовок — device ID
- WebSocket: `ws://host/ws/stream/{deviceId}`
- SPS/PPS кеширование — мгновенный старт для нового viewer
- Adaptive bitrate — автоподстройка при перегрузке

> **Важно:** Для стриминга необходимо, чтобы Android-агент был online и имел активное MediaProjection разрешение.

---

## 6. Task Engine — Движок задач

**Маршрут:** `/tasks`

### Элементы страницы

| Элемент | Описание |
|---------|----------|
| **Task List** | Таблица задач с статусом, устройством, временем запуска/завершения |
| **Gantt Chart** | Диаграмма Ганта — визуализация batch-исполнения по устройствам и времени |
| **Status Filter** | Фильтрация по статусу задачи |
| **Workflow Visualizer** | Визуальное отображение DAG-топологии (read-only) |

### Статусы задач

| Статус | Цвет | Описание |
|--------|------|----------|
| `PENDING` | Серый | Создана, ожидает очереди |
| `QUEUED` | Синий | В очереди Redis TaskQueue |
| `ASSIGNED` | Голубой | Назначена устройству |
| `RUNNING` | Жёлтый | Выполняется |
| `SUCCESS` | Зелёный | Успешно завершена |
| `FAILED` | Красный | Ошибка выполнения |

### Gantt Chart

```
Время →   10:00  10:01  10:02  10:03  10:04
Device-1  ████████████░░░░░                    ✓ SUCCESS
Device-2       ░░░████████████████             ✓ SUCCESS
Device-3            ░░░░░████████████████      ✗ FAILED
Device-4                 ░░░████████████████   ⏳ RUNNING
```

- **Горизонтальная ось**: время
- **Вертикальная ось**: устройства
- **Цвет полосы**: статус задачи
- **Клик по полосе**: открывает Inspector с деталями задачи

### Детали задачи (Inspector)

| Поле | Описание |
|------|----------|
| Task ID | UUID задачи |
| Script | Название скрипта |
| Device | Имя устройства |
| Status | Текущий статус |
| Started/Finished | Время начала и окончания |
| Wave | Номер волны (при batch-исполнении) |
| Result | JSON-объект результата |
| Error | Сообщение об ошибке (при FAILED) |
| Node Execution Log | Пошаговый лог каждого узла DAG |

#### Node Execution Log

```
┌─────────────────────────────────────────────────────┐
│ #1  Tap (540, 960)           ✓  12ms               │
│ #2  Sleep (1000ms)           ✓  1001ms              │
│ #3  Swipe (100,500→900,500)  ✓  320ms               │
│ #4  Screenshot               ✓  89ms   [📷 View]    │
│ #5  Condition (ctx.ok)       ✓  2ms                  │
│ #6  Lua (process_data)       ✗  45ms   Error: ...   │
└─────────────────────────────────────────────────────┘
```

---

## 7. Orchestration — Визуальный DAG-редактор

**Маршрут:** `/orchestration`

Визуальный построитель пайплайнов на базе React Flow. Drag-and-drop создание сложных автоматизаций.

### Toolbar

| Кнопка | Действие |
|--------|----------|
| **New Script** | Диалог создания нового скрипта (ввод имени) |
| **Save** | Сохранение текущего графа как JSON |
| **Validate** | Проверка DAG на циклы и отсутствие коннекторов |
| **Run** | Запуск скрипта (открывает RunScriptModal) |
| **Zoom In/Out** | Масштабирование холста |
| **Fit View** | Автоподгонка zoom под весь граф |

### Типы узлов (Nodes)

| Тип | Иконка | Описание | Параметры |
|-----|--------|----------|-----------|
| **Tap** | 👆 | Нажатие на координаты | `x: number, y: number` |
| **Swipe** | ↔️ | Свайп от точки A к точке B | `x1, y1, x2, y2, duration_ms` |
| **Sleep** | ⏱️ | Пауза | `duration_ms` (по умолчанию 1000) |
| **Lua** | 🔧 | Пользовательский Lua-код | `code: string` (Monaco Editor) |
| **Condition** | 🔀 | Ветвление по условию | `expression: string` |
| **Screenshot** | 📷 | Снимок экрана | `save_to_results: boolean` |

### Работа с редактором

```
1. Перетащи узел из палитры на холст
2. Соедини выходной порт одного узла с входным другого
3. Настрой параметры узла в боковой панели справа
4. Нажми «Validate» — проверка на циклы и полноту связей
5. Нажми «Save» — граф сохраняется на сервере
6. Нажми «Run» — открывается RunScriptModal

     ┌─────┐    ┌─────────┐    ┌──────────┐
     │ Tap │───→│  Sleep   │───→│Screenshot│
     └─────┘    └─────────┘    └──────────┘
                                     │
                               ┌─────▼──────┐
                               │ Condition   │
                               └──┬──────┬──┘
                            true  │      │ false
                           ┌──────▼┐  ┌──▼──────┐
                           │  Lua  │  │  Swipe   │
                           └───────┘  └─────────┘
```

### Sidebar свойств узла

При выборе узла на холсте появляется панель справа:

| Поле | Пример | Описание |
|------|--------|----------|
| **Node Type** | `Tap` | Read-only |
| **Label** | `Open App` | Произвольное имя узла |
| **X** | `540` | Координата X нажатия |
| **Y** | `960` | Координата Y нажатия |
| **Timeout** | `5000` | Таймаут выполнения (ms) |

---

## 8. Scripts — Библиотека скриптов

**Маршрут:** `/scripts`

### Таблица скриптов

| Колонка | Описание |
|---------|----------|
| **Name** | Название скрипта |
| **Nodes** | Количество узлов DAG (badge) |
| **Updated** | Дата последнего изменения |
| **Edit** | Ссылка → `/scripts/builder?id={id}` |
| **Run** | Кнопка → **RunScriptModal** |

### RunScriptModal — Диалог запуска

Главный диалог запуска скрипта на устройствах:

```
┌──────────────────────────────────────────────┐
│  Run: "Auto Login Script"                    │
│                                              │
│  Target mode:                                │
│  ○ All devices                               │
│  ○ By group     [▼ Production Fleet]         │
│  ○ By location  [▼ Office Moscow]            │
│  ● Select manually                           │
│                                              │
│  ┌─ Devices ──────────────────────────────┐  │
│  │ 🔍 [Search devices...]                 │  │
│  │                                        │  │
│  │ ☑ pixel-5-office-1     online   98% 🔋│  │
│  │ ☑ samsung-a52-test     online   45% 🔋│  │
│  │ ☐ redmi-note-12        offline        │  │
│  │ ☑ emulator-ld-001      online   100%🔋│  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Priority:    [████████░░] 8/10              │
│  Wave size:   [10] devices per wave          │
│  Wave delay:  [5000] ms between waves        │
│                                              │
│            [Cancel]    [Execute 🚀]          │
└──────────────────────────────────────────────┘
```

| Параметр | Описание | Значение по умолчанию |
|----------|----------|-----------------------|
| **Target mode** | Способ выбора устройств | `Select manually` |
| **Priority** | Приоритет задачи (0-10, слайдер) | 5 |
| **Wave size** | Кол-во устройств в одной волне | 10 |
| **Wave delay** | Пауза между волнами (ms) | 5000 |

> **Wave Execution:** При wave_size=10 и 50 устройствах — скрипт выполнится в 5 волн: первые 10, пауза 5с, следующие 10 и т.д. Это предотвращает перегрузку backend'а.

### Script Builder (`/scripts/builder`)

Тот же DAG-редактор, что и `/orchestration`, но для создания и редактирования скриптов. При переходе из таблицы скриптов с `?id={id}` — загружает существующий граф для редактирования.

---

## 9. VPN / Tunneling — Управление туннелями

**Маршрут:** `/vpn`

Управление AmneziaWG VPN-туннелями. Страница организована в 6 вкладок (Tabs).

### Вкладки

#### Tab 1 — Pool (Пул IP-адресов)

| Карточка | Значение | Описание |
|----------|----------|----------|
| **Total IPs** | `256` | Всего IP в пуле |
| **Allocated** | `142` | Выделено устройствам |
| **Available** | `114` | Свободно |
| **Active Tunnels** | `98` | Подключены прямо сейчас |
| **Stale Tunnels** | `3` | Handshake > 5 минут |
| **Utilization** | `55.5%` | Процент использования |

#### Tab 2 — Health (Здоровье)

| Элемент | Описание |
|---------|----------|
| **Overall Status** | Badge: `healthy` (🟢) / `degraded` (🟡) / `down` (🔴) |
| **Check Cards** | Отдельная карточка для каждой подсистемы |

Подсистемы проверки:
- WireGuard Interface
- DNS Resolution
- Key Rotation
- Certificate Validity

#### Tab 3 — Agents

Список VPN-пиров (серверов):

| Колонка | Описание |
|---------|----------|
| Name | Имя пира |
| Endpoint | IP-адрес |
| Clients | Кол-во подключённых клиентов |
| RX / TX | Входящий / исходящий трафик |
| Status | online / offline |
| Uptime | Время безотказной работы |

#### Tab 4 — Kill Switch

| Элемент | Описание |
|---------|----------|
| **Toggle** | Включить/отключить Kill Switch для всех туннелей |
| **Status** | Текущее состояние: Active / Inactive |

> **Kill Switch:** При активации все VPN-туннели мгновенно завершаются. Используется в экстренных ситуациях (компрометация ключей, атака).

#### Tab 5 — Rotate (Ротация ключей)

| Кнопка | Действие |
|--------|----------|
| **Rotate All Keys** | POST `/api/v1/vpn/rotate-keys` — перегенерация всех WireGuard keypairs |

#### Tab 6 — Batch

Пакетные операции над туннелями.

### Throughput Chart

Recharts Line/Area таблица трафика — RX/TX в Mbps за последние 24 часа.

---

## 10. Groups — Группы устройств

**Маршрут:** `/groups`

### Таблица групп

| Колонка | Описание |
|---------|----------|
| **Name** | Название группы + цветовой индикатор |
| **Devices** | Формат: `5/12` (5 online из 12 всего) |
| **Status** | `ONLINE` (все online), `DEGRADED` (часть offline), `OFFLINE` (все offline), `EMPTY` |
| **Edit** | Кнопка → диалог редактирования |
| **Delete** | Кнопка → подтверждение удаления |

### Диалог создания группы

| Поле | Тип | Обязательное | Валидация |
|------|-----|:---:|-----------|
| **Name** | text | ✓ | 1-255 символов |
| **Description** | textarea | ✗ | До 1000 символов |
| **Color** | color picker | ✗ | Hex-формат (#RRGGBB) |

### Диалог редактирования группы

Те же поля, что и при создании: `Name`, `Description`, `Color`. Загружаются текущие значения.

> **Примечание:** Группы поддерживают вложенность (`parent_group_id`), однако в текущем UI вложенность отображается плоским списком.

---

## 11. Locations — Геолокации

**Маршрут:** `/locations`

### Таблица локаций

| Колонка | Описание |
|---------|----------|
| **Name** | Название локации + цвет |
| **Address** | Физический адрес (если задан) |
| **Devices** | Количество привязанных устройств |
| **Edit** | Кнопка → диалог редактирования |
| **Delete** | Кнопка → подтверждение удаления |

### Диалог создания локации

| Поле | Тип | Обязательное | Описание |
|------|-----|:---:|----------|
| **Name** | text | ✓ | Название (1-255 символов) |
| **Description** | textarea | ✗ | Описание |
| **Color** | color picker | ✗ | Цвет-маркер |
| **Address** | text | ✗ | Физический адрес |

### Привязка устройств

Устройства привязываются к локации через:
1. Fleet Matrix → контекстное меню → «Assign Location»
2. API: `POST /api/v1/locations/{id}/devices/assign`

---

## 12. Discovery — Сканер сети

**Маршрут:** `/discovery`

Автоматическое обнаружение Android-устройств в локальной сети.

### Форма сканирования

| Поле | Тип | Описание | Пример |
|------|-----|----------|--------|
| **Subnet** | text (CIDR) | Подсеть для сканирования | `192.168.1.0/24` |
| **Ports** | text (comma-sep) | ADB-порты | `5555,5037` |
| **Auto-register** | checkbox | Автоматически регистрировать | ✓ по умолчанию |
| **Кнопка «Scan»** | button | Запустить сканирование | — |

### Результаты

```
Found 12 devices in 192.168.1.0/24:

IP Address      Port   Android ID          Status    Action
192.168.1.101   5555   abc123def456...     New       [Register]
192.168.1.102   5555   xyz789ghi012...     Exists    già registrato
192.168.1.103   5555   qwe345rty678...     New       [Register]
...

[Register All New] (при auto_register=false)
```

> **Auto-register:** Если включено — обнаруженные устройства автоматически добавляются в систему без ручного подтверждения. Рекомендуется для LDPlayer-ферм.

---

## 13. Users — Управление пользователями

**Маршрут:** `/users`

### Таблица пользователей

| Колонка | Описание |
|---------|----------|
| **Email** | Email пользователя |
| **Role** | Роль (см. RBAC) |
| **Created** | Дата создания аккаунта |
| **Status** | Active (🟢) / Inactive (🔴) |
| **Actions** | Change role, Deactivate |

### Кнопка «Add User»

```
┌─────────────────────────────────┐
│  Create User                    │
│                                 │
│  Email:    [________________]   │
│  Password: [________________]   │
│  Role:     [▼ device_manager ]  │
│                                 │
│         [Cancel]  [Create]      │
└─────────────────────────────────┘
```

| Поле | Валидация |
|------|-----------|
| **Email** | Обязательное, формат email |
| **Password** | Обязательное, минимум 8 символов |
| **Role** | viewer / script_runner / device_manager / org_admin / org_owner |

### Действия с пользователем

| Действие | Описание |
|----------|----------|
| **Change Role** | Выпадающий список ролей → `PUT /api/v1/users/{id}/role` |
| **Deactivate** | Подтверждение → `DELETE /api/v1/users/{id}` |

---

## 14. Audit Log — Журнал безопасности

**Маршрут:** `/audit`

Enterprise-уровень аудита всех действий в системе.

### Элементы страницы

| Элемент | Описание |
|---------|----------|
| **Query Builder** | Строка поиска с DSL-синтаксисом |
| **Таблица событий** | Логи с иконками статуса |
| **Export** | Кнопка экспорта логов |
| **Audit Drawer** | Правая панель с деталями события |

### Query Builder DSL

| Синтаксис | Описание | Пример |
|-----------|----------|--------|
| `status:FAILED` | Фильтр по статусу | Только ошибки |
| `user:admin@` | Фильтр по пользователю | Действия конкретного юзера |
| `action:delete` | Фильтр по действию | Все удаления |
| `resource:device` | Фильтр по ресурсу | Операции с устройствами |
| Свободный текст | Полнотекстовый поиск | Любое совпадение |

```
Пример: status:FAILED action:delete user:admin@company.com
→ Покажет все неудачные попытки удаления от admin
```

### Таблица аудита

| Колонка | Описание |
|---------|----------|
| **Timestamp** | Время события (ISO) |
| **User** | Email или ID пользователя |
| **Action** | create / update / delete / login и т.д. |
| **Resource** | device / script / task / user / vpn |
| **Status** | ✓ SUCCESS / ✗ FAILED / ⚠ WARNING |
| **IP** | IP-адрес клиента |

**Клик по строке** → Audit Drawer с полными деталями:
- Request body
- Response code
- User-Agent
- Duration

---

## 15. Sys Logs — Logcat просмотрщик

**Маршрут:** `/logs`

Просмотр Android logcat с устройств в реальном времени.

### Элементы управления

| Элемент | Описание |
|---------|----------|
| **Device Selector** | Выпадающий список устройств |
| **Level Filter** | V (Verbose) / D (Debug) / I (Info) / W (Warning) / E (Error) / A (Assert) |
| **Search** | Полнотекстовый фильтр по логам |
| **Auto-refresh** | Toggle включает автообновление каждые 3 секунды |

### Отображение логов

```
2026-03-02 10:15:32.456  I  ActivityManager: Start proc com.app.target
2026-03-02 10:15:32.789  D  SphereAgent: Heartbeat sent, battery=95%
2026-03-02 10:15:33.012  W  InputDispatcher: Slow dispatch (120ms)
2026-03-02 10:15:33.456  E  SphereAgent: WebSocket reconnect failed: timeout
```

| Уровень | Цвет | Описание |
|---------|------|----------|
| V | Серый | Verbose — максимальная детализация |
| D | Голубой | Debug — отладочная информация |
| I | Зелёный | Info — штатная информация |
| W | Жёлтый | Warning — предупреждения |
| E | Красный | Error — ошибки |
| A | Тёмно-красный | Assert — фатальные ассерты |

---

## 16. Monitoring — Мониторинг инфраструктуры

**Маршрут:** `/monitoring`

### Метрики системы (автообновление каждые 10 секунд)

| Карточка | Описание | Визуализация |
|----------|----------|-------------|
| **CPU Usage** | Загрузка процессора | Sparkline |
| **RAM Usage** | Использование памяти | Sparkline |
| **Redis** | Hit rate, memory, connections | Sparkline |
| **Network** | RX/TX throughput | Sparkline |

### Cluster Heatmap

Тепловая карта здоровья узлов кластера:

```
┌────────────────────────────────────┐
│  Node-1  [🟢🟢🟢🟢🟢]  CPU: 23%  │
│  Node-2  [🟢🟢🟢🟡🟡]  CPU: 67%  │
│  Node-3  [🟢🟢🟢🟢🟢]  CPU: 12%  │
│  Node-4  [🔴🔴🔴🔴🔴]  OFFLINE   │
└────────────────────────────────────┘
```

---

## 17. Updates — OTA обновления

**Маршрут:** `/updates`

Управление OTA-обновлениями Android-агента.

### Таблица релизов

| Колонка | Описание |
|---------|----------|
| **Platform** | Android |
| **Flavor** | production / beta / staging |
| **Version** | Версия (code + name) |
| **SHA256** | Хеш APK для валидации |
| **Mandatory** | Обязательное обновление (✓/✗) |
| **Changelog** | Описание изменений |
| **Download** | Ссылка на скачивание APK |
| **Push OTA** | Кнопка отправки обновления на выбранные устройства/группы |

### Push OTA

При нажатии «Push OTA» создаётся задача:
```
POST /api/v1/tasks {
  device_id: "...",
  script_id: "ota-update",
  input_params: { version: "4.5.0", url: "https://...", sha256: "..." }
}
```

---

## 18. Webhooks — n8n интеграция

**Маршрут:** `/webhooks`

Настройка webhook-уведомлений для интеграции с n8n и внешними системами.

### Таблица вебхуков

| Колонка | Описание |
|---------|----------|
| **Name** | Название вебхука |
| **URL** | Endpoint для отправки событий |
| **Events** | Список событий: `task.completed`, `device.online`, `device.offline` |
| **Active** | Toggle включения/отключения |
| **Created** | Дата создания |
| **Delete** | Кнопка удаления |

### Создание вебхука

```
┌─────────────────────────────────────────────┐
│  Create Webhook                             │
│                                             │
│  Name:    [n8n-task-notifications_________] │
│  URL:     [https://n8n.example.com/webhook] │
│  Events:  [task.completed, device.offline ] │
│  Secret:  [auto-generated________________] │
│                                             │
│              [Cancel]  [Create]              │
└─────────────────────────────────────────────┘
```

### Поддерживаемые события

| Событие | Описание |
|---------|----------|
| `device.online` | Устройство подключилось |
| `device.offline` | Устройство отключилось |
| `task.completed` | Задача завершена (SUCCESS/FAILED) |
| `task.started` | Задача начала выполнение |
| `vpn.tunnel.up` | VPN-туннель поднят |
| `vpn.tunnel.down` | VPN-туннель упал |
| `batch.completed` | Batch-исполнение завершено |

---

## 19. Settings — Настройки пользователя

**Маршрут:** `/settings`

Три вкладки: **Profile**, **MFA**, **API Keys**.

### Tab 1 — Profile

| Поле | Описание |
|------|----------|
| **Email** | Read-only, отображает текущий email |
| **Role** | Read-only, текущая роль |
| **Created** | Дата создания аккаунта |

### Tab 2 — MFA (Multi-Factor Authentication)

| Элемент | Описание |
|---------|----------|
| **Setup Button** | Начать настройку TOTP |
| **QR Code** | QR-код для Google Authenticator / Authy |
| **Secret** | Текстовый ключ (для ручного ввода) + кнопка копирования |
| **TOTP Input** | 6-значный код для верификации |
| **Verify Button** | Подтвердить привязку MFA |

```
Процесс настройки MFA:
1. Нажми «Setup MFA»
2. Отсканируй QR-код в Google Authenticator
3. Введи 6-значный код из приложения
4. Нажми «Verify» → MFA активирован
5. При следующем входе потребуется TOTP-код
```

### Tab 3 — API Keys

| Элемент | Описание |
|---------|----------|
| **Таблица ключей** | name, key_prefix (первые 8 символов), permissions, active, last_used |
| **Create Key** | Кнопка → диалог создания |
| **Revoke** | Кнопка отзыва ключа |

#### Диалог создания API-ключа

```
┌─────────────────────────────────────┐
│  Create API Key                     │
│                                     │
│  Name:  [CI/CD Pipeline Key_______] │
│                                     │
│  Permissions:                       │
│  ☑ devices:read                     │
│  ☑ devices:write                    │
│  ☐ scripts:execute                  │
│  ☐ admin:full                       │
│                                     │
│         [Cancel]  [Create]          │
│                                     │
│  ⚠️ Скопируй ключ сейчас!           │
│  Он больше не будет показан.        │
│  [sk-abc123...xyz789]  [📋 Copy]    │
└─────────────────────────────────────┘
```

---

## 20. Навигация и горячие клавиши

### NOC Sidebar (17 пунктов)

| # | Пункт | Маршрут | Иконка |
|---|-------|---------|--------|
| 1 | Overview | `/dashboard` | LayoutDashboard |
| 2 | Infrastructure | `/monitoring` | Server |
| 3 | Fleet Matrix | `/devices` | Cpu |
| 4 | Device Stream | `/stream` | Video |
| 5 | Task Engine | `/tasks` | ListTodo |
| 6 | Orchestration | `/orchestration` | GitBranch |
| 7 | Tunneling | `/vpn` | Shield |
| 8 | Scripts | `/scripts` | Code |
| 9 | Groups | `/groups` | FolderOpen |
| 10 | Locations | `/locations` | MapPin |
| 11 | Discovery | `/discovery` | Radar |
| 12 | Users | `/users` | Users |
| 13 | Audit Log | `/audit` | ScrollText |
| 14 | Sys Logs | `/logs` | Terminal |
| 15 | Updates | `/updates` | Download |
| 16 | Webhooks | `/webhooks` | Link |
| 17 | Sys Config | `/settings` | Settings |

### Поведение Sidebar

| Платформа | Поведение |
|-----------|-----------|
| **Desktop** | Свёрнут (w-14, только иконки), раскрывается при наведении мыши (w-56) |
| **Mobile** | Фиксированный оверлей, закрывается при клике на ссылку |

### Горячие клавиши

| Комбинация | Действие |
|-----------|----------|
| `Cmd+K` / `Ctrl+K` | Открыть Command Palette |
| `Escape` | Закрыть модальное окно / палитру / inspector |
| `Enter` | Подтвердить форму |

### Command Palette (Cmd+K)

```
┌──────────────────────────────────────────┐
│  🔍 Type a command...                    │
│                                          │
│  ── Navigation ──                        │
│  → Go to Overview                        │
│  → Go to Fleet Matrix                    │
│  → Go to Audit Log                       │
│  → Go to Monitoring                      │
│  → Go to Scripts                         │
│                                          │
│  ── Preferences & Settings ──            │
│  🎨 UI Configuration                     │
│                                          │
│  ── Quick Actions ──                     │
│  📋 Open Inspector                       │
│  🔄 Refresh Data                         │
└──────────────────────────────────────────┘
```

---

## Приложение A — Роли и права доступа (RBAC)

### Матрица разрешений

| Действие | viewer | script_runner | device_manager | org_admin | org_owner |
|----------|:------:|:---:|:---:|:---:|:---:|
| Просмотр устройств | ✓ | ✓ | ✓ | ✓ | ✓ |
| Просмотр стримов | ✓ | ✓ | ✓ | ✓ | ✓ |
| Запуск скриптов | — | ✓ | ✓ | ✓ | ✓ |
| Создание задач | — | ✓ | ✓ | ✓ | ✓ |
| Управление устройствами | — | — | ✓ | ✓ | ✓ |
| Управление группами | — | — | ✓ | ✓ | ✓ |
| Управление локациями | — | — | ✓ | ✓ | ✓ |
| Bulk-операции | — | — | ✓ | ✓ | ✓ |
| Удаление устройств | — | — | — | ✓ | ✓ |
| Управление VPN | — | — | — | ✓ | ✓ |
| Управление пользователями | — | — | — | — | ✓ |
| Настройка вебхуков | — | — | — | ✓ | ✓ |
| Kill Switch VPN | — | — | — | ✓ | ✓ |
| Аудит логов | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## Приложение B — API эндпоинты

### Управление устройствами

```http
GET    /api/v1/devices                         # Список (фильтры: status, tags, group_id, search, page, per_page)
GET    /api/v1/devices/{id}                    # Детали устройства
PUT    /api/v1/devices/{id}                    # Обновление ({ name })
DELETE /api/v1/devices/{id}                    # Удаление
POST   /api/v1/devices/{id}/connect            # Подключение ADB
POST   /api/v1/bulk-action                     # Массовые операции ({ device_ids, action })
```

### Группы и локации

```http
GET    /api/v1/groups                          # Список
POST   /api/v1/groups                          # Создание
PUT    /api/v1/groups/{id}                     # Обновление
DELETE /api/v1/groups/{id}                     # Удаление
POST   /api/v1/groups/{id}/devices/move        # Перемещение устройств

GET    /api/v1/locations                       # Список
POST   /api/v1/locations                       # Создание
PUT    /api/v1/locations/{id}                  # Обновление
DELETE /api/v1/locations/{id}                  # Удаление
POST   /api/v1/locations/{id}/devices/assign   # Привязка устройств
POST   /api/v1/locations/{id}/devices/remove   # Отвязка устройств
```

### Скрипты и задачи

```http
GET    /api/v1/scripts                         # Список
POST   /api/v1/scripts                         # Создание
PUT    /api/v1/scripts/{id}                    # Обновление
DELETE /api/v1/scripts/{id}                    # Удаление

GET    /api/v1/tasks                           # Список (фильтры: status, device_id, script_id, batch_id)
GET    /api/v1/tasks/{id}                      # Детали + результат + логи
POST   /api/v1/tasks                           # Создание задачи
POST   /api/v1/batches/start                   # Batch запуск
```

### VPN

```http
GET    /api/v1/vpn/peers                       # Список туннелей
GET    /api/v1/vpn/health                      # Статус здоровья
POST   /api/v1/vpn/rotate-keys                 # Ротация ключей
POST   /api/v1/vpn/kill-switch                 # Kill Switch
```

### Аутентификация

```http
POST   /api/v1/auth/login                      # Вход (email + password)
POST   /api/v1/auth/login/verify-mfa           # MFA верификация
POST   /api/v1/auth/mfa/setup                  # Настройка MFA (→ QR + secret)
POST   /api/v1/auth/mfa/verify                 # Подтверждение MFA
POST   /api/v1/auth/logout                     # Выход
GET    /api/v1/auth/api-keys                   # Список API-ключей
POST   /api/v1/auth/api-keys                   # Создание API-ключа
DELETE /api/v1/auth/api-keys/{id}              # Отзыв API-ключа
```

### Пользователи

```http
GET    /api/v1/users                           # Список (page, per_page)
POST   /api/v1/users                           # Создание
PUT    /api/v1/users/{id}/role                 # Изменение роли
DELETE /api/v1/users/{id}                      # Деактивация
```

### Мониторинг и логи

```http
GET    /api/v1/monitoring/metrics              # Системные метрики
GET    /api/v1/monitoring/nodes                # Статус узлов кластера
GET    /api/v1/logs?device_id={id}             # Logcat с устройства
GET    /api/v1/audit/logs                      # Аудит (query DSL)
```

### Discovery и Webhooks

```http
POST   /api/v1/discovery/scan                  # Сканирование подсети
GET    /api/v1/n8n/webhooks                    # Список вебхуков
POST   /api/v1/n8n/webhooks                    # Создание
DELETE /api/v1/n8n/webhooks/{id}               # Удаление
```

### WebSocket

```
WS     /ws/stream/{deviceId}                   # H.264 видеопоток
WS     /ws/subscribe/fleet-events              # События флота (online/offline/task)
```

---

<div align="center">

*Sphere Platform NOC — Enterprise Android Device Management*

**Вопросы и предложения** → [GitHub Issues](https://github.com/RootOne1337/sphere-platform/issues)

</div>
