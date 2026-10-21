# VPN: проверка интерфейса исходной версии

Это проверка компонентов с синтетическими данными. Установленные UI `5cbb4bba`,
API `15ce2b62` и APK83 этим этапом не заменены. Рабочие VPN-профили не использовались
в браузерной фикстуре; сетевые изменения отключены. JSON с хешами исходников,
изображений, результатами и ограничениями:
[VPN-WORKSPACE-REDESIGN-SOURCE.json](VPN-WORKSPACE-REDESIGN-SOURCE.json).

## Изменения

- Четыре раздела вместо одной длинной страницы. Android-подключения открываются первыми.
- Карточки профилей с протоколом, версией, политикой приложений и историей.
- Импорт с выбором файла, явными полями протокола/IPv6 и закреплёнными действиями.
- Диагностика с отдельными счётчиками и вкладками соединения/идентификаторов.
- Единое оформление истории, архива и подтверждений операций на Radix/shadcn.
- Мобильные строки устройств, перенос длинных имён, доступный размер действий.
- Вступление вкладок учитывает `prefers-reduced-motion`; искусственных бликов нет.

При проверке исправлены переполнение IPv6 select на desktop, перенос двух основных
кнопок в две строки на телефоне, мелкая смешанная русско-английская типографика
инфраструктуры. Новый отчёт, пришедший между тиками локальных часов, теперь сразу
считается свежим; сохранённые данные всё равно устаревают без следующего ответа.

Использованы существующие зависимости проекта. Официальные ориентиры:
[shadcn blocks](https://v3.shadcn.com/blocks),
[Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog),
[Radix Tabs](https://www.radix-ui.com/themes/docs/components/tabs).
Новый dashboard-пакет или тяжёлая библиотека эффектов не добавлялись.

## Экраны

1440×900 и 390×844, реальные theme tokens neo-dark/sandstone, локальные Inter и
JetBrains Mono из основного layout. Dashboard shell не включён в отдельную фикстуру.
Демонстрационные значения не являются телеметрией PH030.

| Экран | Desktop | Телефон |
|---|---|---|
| Подключения | [Тёмная тема](assets/vpn-workspace/final-connections-dark-desktop.png) | [Песочная тема](assets/vpn-workspace/final-connections-sandstone-mobile.png) |
| Профили | [Тёмная тема](assets/vpn-workspace/final-profiles-dark-desktop.png) | [Песочная тема](assets/vpn-workspace/final-profiles-sandstone-mobile.png) |
| Импорт | [Песочная тема](assets/vpn-workspace/final-import-sandstone-desktop.png) | [Песочная тема](assets/vpn-workspace/final-import-sandstone-mobile.png) |
| Диагностика | [Тёмная тема](assets/vpn-workspace/final-diagnostics-dark-desktop.png) | [Тёмная тема](assets/vpn-workspace/final-diagnostics-dark-mobile.png) |
| Инфраструктура | [Песочная тема](assets/vpn-workspace/final-infrastructure-sandstone-desktop.png) | [Песочная тема](assets/vpn-workspace/final-infrastructure-sandstone-mobile.png) |

Дополнительно: [история версий](assets/vpn-workspace/final-versions-sandstone-desktop.png),
[архивирование](assets/vpn-workspace/final-archive-sandstone-desktop.png).

На 390 px document width равна viewport width. В мобильном импорте header заканчивается
на 144 px, footer начинается на 766 px; внутренний body 622 px прокручивает 873 px
содержимого. На desktop ширина body и scroll width равны 766 px. Это измерения
браузерного layout, не доказательство поведения клавиатуры или touch на реальном телефоне.

## Проверки и оставшиеся шаги

TypeScript и 61 тест восьми VPN frontend suites прошли. Десять targeted backend tests
проверили sealed profile delivery и повтор списка устройств без coverage; Ruff прошёл.
Полный CI на базовом исходнике `61df5729` подтвердил 2600 frontend tests, но завершился
с одной backend performance failure: 203 мс при неизменённом лимите 200 мс; остальные
4389 прошли, 63 пропущены. Этот запуск не считается успешным допуском к упаковке.

Нужны полный прогон конечного исходника, immutable UI/API packages, штатная миграция
каталога и key recovery, проверенная runtime DB role, single-APK device pilot.
Сейчас runtime SQL login имеет superuser/BYPASSRLS: tenant RLS была проверена отдельно
с non-owner ролью, но эти испытания не означают, что установленный API работает под ней.
Server journal, уникальные client-key leases и общий execution для UI/scripts/orchestration
остаются открыты. Визуальная готовность не закрывает эти пункты.
