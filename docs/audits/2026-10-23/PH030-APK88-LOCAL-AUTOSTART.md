# PH030: локальный APK88 и восстановление VPN после перезагрузки

[Машинная квитанция](PH030-APK88-LOCAL-AUTOSTART.json).
Наблюдение 23 октября 2026 года; актуальный package readback — 11:12 UTC.
UI `a239baa2` / API `1afdc529` сохранены. Только auto-ph-030 обновлён до
`1.2.88-dev /10288`; PH010/PH011/PH025 остаются на ранее подтверждённом APK85,
17 offline не обновлены. Общая production-приёмка не заявляется.

## Результат и причина дефекта

После одного настоящего reboot PH030 VPN **восстановился автоматически**.
Доказательства включают смену kernel boot ID, тот же VPN session ID, новый native
процесс, свежий `HANDSHAKE_CONFIRMED`, действующие правила обеих IP-семей, TUN index
и HTTPS в браузере с VPN-IP. Ручного APPLY или нового recipient после reboot не было.

В APK87 профиль жил только в памяти native-процесса. После reboot kernel TUN и
правила исчезали, а старый `ALLOWED` на диске оставался. Его нельзя было считать
защитой или повторно применять без проверки. [Предыдущий опыт и ручное
восстановление](PH030-APK87-DELIVERY-AND-REBOOT.md) сохранены как историческая квитанция.

APK88 сохраняет active/paused/disabled intent в приватном CE storage:
AES-256-GCM, AndroidKeyStore, случайный nonce и package-bound AAD. Профиль не
сохраняется открытым текстом. Подтверждённый guard связан с kernel boot ID.
Восстановление разрешено только после доказанного нового boot, при совпадении
UID/policy/session и отсутствии старых kernel resources. Сначала подтверждаются
DROP и blackhole routes, затем поднимается native VPN. UNKNOWN, INTENT, legacy
record без boot ID, незавершённая мутация и same-boot restart требуют согласования
состояния; их автоматический повтор не разрешён.

Явное отключение оставляет stop marker; включить автозапуск снова может только
успешный новый APPLY. Ошибка чтения optional restart file не роняет основной
management startup. Web получает существующую фазу `APPLYING` с причиной
`vpn_restoring_after_boot`, затем свежие native snapshots; новая несовместимая
фаза API не вводилась. BootReceiver и native service входят в тот же APK.

## Сборка и адресная установка

Source `6ad0df5fbcc3590ae9c63fe6922db178b45aeee1`.
APK SHA-256 `355af6f5ecc6697bd8fee66ff9f085bdbf9841e80bb201f8d48515a1ac7e9bca`,
73 153 198 bytes. Прежний сертификат подписи и библиотеки всех трёх ABI проверены.
SHA установленного пакета независимо прочитан после OTA и после реальной загрузки.

| Локальная проверка | Результат |
| --- | --- |
| Четыре ordinary unit-варианта | По 1276 тестов, 3 skipped, 0 failures/errors |
| Configured DevDebug и EnterpriseDebug | По 1290 тестов, 3 skipped, 0 failures/errors |
| Lint и assemble обоих configured debug-вариантов | Успешно |
| Итог | 7684 исполнения, включая 18 skipped; 0 failures/errors |
| Ресурсы | Один worker, Java heap 1536 MiB; существующие guards сохранены |
| GitHub | Новых jobs/dispatch/rerun — 0 |

Использован существующий native artifact `12458170692` из validation `39844420660`:
digest и manifest проверены, native source относительно него не менялся. Это
переиспользование native-библиотек, а не перенос полного CI87 на новое Android-дерево.
Полный release packaging/R8/denial suite и профиль Android CI с порогом 12 GiB
для APK88 не заявляются. Начальная локальная попытка `b1daf2b1` остановлена до
упаковки ради исправления wire contract и защиты management startup; её частичные
результаты не использованы как окончательная приёмка.

OTA выполнена через адресный canary grant только PH030. Старый UID guard удержан
на обновлении. Во время передачи native guard действовал отдельный DROP обеих
семей, затем проверены новые kernel rules/routes/TUN; временный guard удалён.
Android journal не редактировался, UNKNOWN не очищался. Данные игры, обычный
update-канал и другие устройства не менялись; ADB install не использовался.

## Проверки после настоящего reboot

| Проверка | Подтверждённый конечный результат |
| --- | --- |
| Kernel boot ID | Изменился; guard связан с новым boot |
| Сессия | Та же; encrypted restart state обновлён, native PID новый |
| Интернет | Свежая HTTPS-страница с query `sphere_probe=apk88_real_boot`, VPN-IP `64.145.94.74` |
| Sphere bypass | UID 10060 исключён; management, прямые video/input работают |
| Политика | App UID 10000–10059 и 10061–99999; IPv6 заблокирован |
| Прямое PC-видео | 1121 декодированный кадр за 20,005 с, около 55,09 FPS |
| RGB-наблюдения | 101, около 5 Гц; один последний кадр без накопления очереди |
| Непрерывный ввод | Один жест 3 с, все 6 DOWN/MOVE/UP подтверждены native receipts |
| Освобождение | Participant close подтверждён, указатель не удерживается |
| Серверное видео | 0 байт bootstrap и после handover в этом опыте |

SCTP smoothed RTT 6,063 мс, retransmissions 0; последний action ACK RTT 15,15 мс.
Receiver selection age p95 21,832 мс, max 36,664 мс относится к уже декодированному
кадру, **не** полной задержке Android capture→модель или действие→изображение.
UDP host/prflx с private addresses не доказывает физически кратчайший LAN-путь.
Телефонный браузер этим опытом не принят. Модель ИИ не запускалась.
Сохранены отдельные конечные кадры/квитанции; непрерывного архива кадров нет.

## Ограничения и следующий этап

- Проверен один **ACTIVE reboot**. Paused/disabled имеют unit coverage, отдельные
  физические reboot-тесты ещё не выполнены.
- CE unlock и запуск агента не доказывают отсутствие исходящего трафика от подачи
  питания до установки guard. Ранний boot fail-closed barrier остаётся открытым.
  System UIDs 0–9999 не входят в этот custom UID guard.
- Временный ciphertext PC-шлюз остаётся зависимостью; lease заканчивается
  **23 октября 19:08:05 UTC /24 октября 00:08:05 UTC+5**. Он не продлевался,
  новые provider peers не создавались. Direct Android WAN и production HA открыты.
- Same-boot process death/UNKNOWN требуют явного согласования; не очищать журнал
  ради зелёного статуса и не повторять неопределённые операции.
- Длительный soak, смена сети, телефонный browser/control и production VPN SLA
  остаются отдельной приёмкой. Готовность универсальной навигации ИИ не заявляется.

Windows `WinError5` при атомарной замене status file шлюза исправлен отдельным
bounded replace-only retry до 310 мс. Пакеты/команды не повторяются. 16 изолированных
тестов, включая реальный UDP и transient/permanent denial, и Ruff прошли.

Android always-on требует собственного сохранения конфигурации и восстановления
соединения: [официальное руководство](https://developer.android.com/develop/connectivity/vpn).
В [AOSP Android 9](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-9.0.0_r1/services/core/java/com/android/server/connectivity/Vpn.java)
`setVpnForcedLocked` исключает UID самого VPN package из kernel lockdown ranges.
Это кандидат для отдельной проверки ранней защиты одного APK; совместимость
management/DNS/WebRTC на данном эмуляторе этим чтением не доказана. Текущий native
readiness отвергает lockdown: системные настройки в этом опыте не включались.

Следующая транспортная приёмка должна закрыть прямой Android WAN/долговечный шлюз,
раннюю boot-защиту и телефонный клиент. После неё можно продолжать ИИ с измерением
возраста исходного кадра и непрерывным удержанием ввода; текущие 5 Гц доказывают
подачу RGB-наблюдений, а не частоту модельных решений.
