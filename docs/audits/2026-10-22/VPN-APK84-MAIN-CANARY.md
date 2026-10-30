# APK84: живой туннель, пауза и дефект пакетной метки

22 октября 2026 · PH011 / Android 9 / основной APK **1.2.84-dev**.
Это первый описанный здесь физический опыт через встроенный `:vpn` сервис,
отдельно от прежних standalone/root-TUN диагностик. **Физический provider APK84
не принят**: handshake есть, обычный TCP/DNS выбранного приложения не проходит.
[Машинная квитанция](VPN-APK84-MAIN-CANARY.json).

## Границы опыта

Выбрано только диагностическое приложение `com.sphereplatform.awgclientprobe`,
UID 10108. Оно не содержит VPN service, Activity или собственного провайдера.
Sphere UID 10082 исключён. Игры и VPN хоста не менялись. Небольшие диагностические
APK/бинарники переданы локальным ADB; установка fixture и все VPN-команды — через
Sphere. Профиль хранится зашифрованно в каталоге, расшифровывается внутри API и
отправляется operation-bound RSA/AES envelope. Plaintext config в shell/relay не передавался.

Для каждого шага локально записаны intent и результат; команда не отправлялась
повторно при неизвестном исходе, offline queue не использовалась. Это конечный
maintainer pilot, **не** серверный production journal/CAS lease. Его реализация
по-прежнему отдельная открытая задача.

## Наблюдения

| Шаг | VPN / выбранное приложение | Sphere |
| --- | --- | --- |
| До применения | IDLE; TCP доступен | TCP доступен |
| Apply | TRANSPORT_READY, затем HANDSHAKE_CONFIRMED; TCP timeout | Управление и TCP доступны |
| Pause | PAUSED_GUARD_HELD; TCP заблокирован | Управление и TCP доступны |
| Resume | TRANSPORT_READY, handshake; TCP/DNS timeout сохраняются | Управление и TCP доступны |
| Временный A/B без mark | TCP и DNS работают через адрес TUN | Работает через обычный интерфейс |
| Возврат исходных mark rules | TCP снова timeout | Работает |
| Disconnect | DISCONNECTED_CONFIRMED; обычный TCP восстановлен | Работает, основной PID не менялся |

A/B ограничивался этим UID. UID routing table с blackhole default и фильтр,
разрешающий только текущий TUN, сохранялись. После опыта исходные правила
восстановлены побайтно; затем штатное отключение удалило собственные UID rule,
route table, filter/mangle jumps и TUN. Guard journal имеет RELEASED.
Профиль архивирован; fixture оставлен для проверки следующего APK.

Сравнение доказывает несовместимость нашей дополнительной packet mark с данным
эмулятором. Точный внутренний механизм vendor/kernel пока не установлен;
это не утверждение о поведении всех Android. Исключены неверный source address,
отбрасывание нашим DROP и включённый Android Data Saver. Сам handshake не
доказывает ни TCP/DNS, ни внешний IP, ни доступность игры.

## Исправление для APK85

Исходный commit `79ba84f9` вводит guard plan **4**: UID-specific FILTER,
ранняя UID routing rule, отдельная таблица с blackhole default, привязка к
имени и kernel ifindex TUN. Новые планы не меняют fwmark/MANGLE. Проверка маршрута
теперь дополнительно подтверждает точный TUN default route перед допуском.

Для безопасного обновления сохранён verifier/release плана 3: старый активный
guard удаляется только по собственному журналу и прежним mark rules, после
подтверждения закрытия старого TUN. Создавать/возобновлять tunnel старым планом
новая версия не может. После RELEASED новый сеанс создаёт план 4. Старые/повреждённые
журналы не превращаются в состояние «всё безопасно».

[Android CI 39764211758](https://github.com/RootOne1337/sphere-platform/actions/runs/39764211758)
запущен для этого source. На момент этой квитанции полный результат ещё не получен,
APK85 не установлен. Его физическая проверка, crash/IPv6/сеть и дальнейшая раскатка
остаются отдельными условиями приёмки. APK84 на остальные устройства не раскатываем.

Для разбора Android policy сверены первичные источники:
[VpnService.Builder](https://developer.android.com/reference/android/net/VpnService.Builder),
[AOSP BandwidthController](https://android.googlesource.com/platform/system/netd/+/refs/heads/android11-d2-release/server/BandwidthController.cpp).
Наличие `bw_costly_tun0` само по себе не доказывает включённый Data Saver — на
PH011 цепочка `bw_data_saver` возвращала трафик, настройка была disabled.
