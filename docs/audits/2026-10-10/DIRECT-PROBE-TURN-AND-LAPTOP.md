# Прямой канал: TURN, сетевой prerequisite и адресное OTA PH030

Срез 10 октября 2026. [Машинный receipt](DIRECT-PROBE-TURN-AND-LAPTOP.json).

PH030 на ноутбуке обновлён **штатным OTA до 1.2.50-dev / 10250**. Фактический
SHA-256 установленного APK совпал с отправленным артефактом. Это подтверждает
установку диагностического модуля, но пока не прямой видеопоток или управление.

## Уточнение топологии

Пользователь подтвердил: PH030 и браузер находятся на ноутбуке без VPN.
VPN работает только на основном ПК. Поэтому изменение маршрутов Amnezia на
основном ПК не является предварительным условием теста browser ↔ APK на ноутбуке.
Проверка из браузера основного ПК к PH030 была бы другой строкой сетевой матрицы.

Сервер авторизует согласование, но не гарантирует достижимость ICE-кандидатов.
Выбранный транспорт требуется измерить. Глобальная сеть может потребовать TURN;
HTTPS-туннель управления сам по себе не является подтверждённым TURN listener.

## Адресное обновление

| Поле | Подтверждённое значение |
| --- | --- |
| Устройство | `auto-ph-030`, `753fd530-2f19-4e5e-98ba-769863678141` |
| Package | `com.sphereplatform.agent.pilot.debug` |
| Было | 1.2.49-dev / 10249, ordinary candidate `d8023bce` |
| Стало | 1.2.50-dev / 10250, source `e54b2fc85f04118a0579e43c9a88e5d0dc09b23d` |
| APK | 57 655 284 bytes |
| SHA-256 APK | `f7bfbc2218acd20a9f9f07b4d0f8d30c14f0547e25fc5eab648881426c69108c` |
| SHA-256 signer | `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f` |
| Release channel | `android-canary`; обычный `android` не изменён |
| Command | `d12673da-18c8-4474-93e3-9674901f911d`, ровно один ID |
| Terminal receipt | `completed`, installed_version_code 10250, recovered_after_process_restart true |
| Установка подтверждена | 05:51:30 UTC terminal receipt; readback SHA подтверждён 05:53:52 UTC |
| Разрешение | Потреблено сервером после завершения; активного grant больше нет |

Первый собранный диагностический APK `0cea768` имел тот же versionCode 10249.
`OtaApkVerifier` требует строго больший номер; обход этой проверки не применялся.
Номер повышен отдельным source commit, затем APK пересобран из чистого Android
дерева с прежней подписью. Это development canary, **не stable 1.3.0**.

Оба debug flavor прошли lint/build и по 1000 JUnit cases: 997 выполнены,
3 skipped, failures/errors 0. Проверены package, версия, signer и SHA.
APK содержит четыре ABI WebRTC JNI, поэтому заметно больше обычного APK.
Наличие JNI в файле не является измерением runtime RAM/CPU.

Файл размещён в существующем managed artifact store. Проверены SHA и размер
в контейнере, а также полный скачанный HTTP body. Anonymous download вернул 401.
Публикация сделана только в `android-canary`, grant выдан только PH030.
ADB install, очистка данных, ручной запуск приложения и fleet OTA не применялись.
Устройство вернулось с прежним ID и новой версией, затем удалённо прочитан хеш
`/data/app/.../base.apk`; конкретный путь не публикуется.

После completed сервер уже потребил grant. Попытка точного revoke вернула 409;
проверка состояния подтвердила отсутствие active grant и сохранённый matching
receipt. Повторный grant/OTA command не создавался. Это особенность readback
очистки, а не неуспешная установка APK.

## Ограниченный TURN contract в source 0cea768

- v1 signaling остаётся совместимым; v2 сначала проверяет пользователя, tenant,
  устройство, RBAC, allowlist и общий device lease, затем выдаёт TURN credentials.
- Coturn REST HMAC credentials действуют 120 секунд. Username содержит opaque
  session nonce и сторону browser/agent, без user/device/tenant identifiers.
- Endpoint выбирает сервер; master key не передаётся клиентам и не пишется в логи.
- Lease peer не продлевается: 30 секунд, до 20 echo samples, максимум 32 stats
  calls и один pending callback; максимум 8 peers, device cooldown 15 секунд.
- Retirement во время ожидания Redis не оставляет grant/lease. Cleanup отдельных
  JavaScript/JNI ресурсов выполняется независимо от исключений соседнего close.
- Обычные APK не включают WebRTC JNI; release-shaped сборки diagnostic source
  запрещены. Нативный diagnostic APK установлен только на явно выбранный PH030.

Optional Linux relay template использует официальный pinned coturn
4.18.0-r0, ограниченные CPU/RAM/pids/logs/allocations/relay ports, read-only root
и private peer restrictions. [Контракт развёртывания](../../../infrastructure/turn/README.md).
Template не поднимает публичный relay на этом ПК автоматически.

## Фактические конечные сетевые проверки

### Маршрут основного ПК

В одном локальном STUN fixture UDP listener был подтверждён внутри контейнера.
Windows loopback получил Binding response. Обращение к physical LAN address
по выбранному Windows маршруту завершилось timeout; тот же socket test с
`IP_UNICAST_IF` на Ethernet получил 40-byte response. Системные маршруты, VPN
и firewall не менялись. Android shell test в этом fixture получил timeout.

Этот результат подтверждает зависимость Windows fixture от выбранного интерфейса.
Он **не устанавливает** точную причину ранее неудачного native WebRTC на PH011
и не описывает ноутбук PH030. Контейнер имел hard deadline 40 секунд и удалён;
существующие контейнеры сохранены.

### REST authentication coturn

Изолированный `network=none` fixture подтвердил: правильный временный credential
дал 4 отправленных / 4 полученных utility messages и exit 0. Неправильный ключ
и истёкший username дали 0 received и bounded timeout. Политика loopback peers
разрешалась только этому fixture; production template её запрещает.

Предыдущие две конфигурации fixture были непригодны из-за allocation quota 486.
В окончательной версии одновременно изменены quota и диапазон relay ports;
отдельная причина среди этих изменений не изолирована. Utility также сообщала
два dropped send attempts: результат не является benchmark потерь, latency,
native WebRTC или production quota fairness. Контейнер удалён по завершении.

### TLS/template preflight

На точном итоговом template отдельный `network=none` fixture подтвердил реальный
UDP socket и TLS handshake с fixture CA/hostname. Wrong key, expired certificate,
wrong hostname, invalid REST key и missing certificate завершились exit 78
**до открытия listener**. Шесть owned containers удалены, публичных listeners нет.

Два устаревших coturn flags обнаружены по реальному startup log и удалены;
повторная проверка итогового template не дала bad-configuration warning.
Доверие публичной certificate chain, доступ извне, native TURN и relay refresh
этой проверкой не подтверждены.

## Следующая source коррекция: панель доступна из обычного веба

Подготовлен authenticated GET
`/api/v1/devices/{device_id}/direct-probe-capabilities`.
Он возвращает только разрешённые профили и фиксированные limits; не создаёт peer,
не выдаёт TURN credentials и не утверждает поддержку со стороны установленного APK.
Чужое/удалённое устройство скрыто, `stream:read` обязателен, ответ `private, no-store`.
WebSocket повторно проверяет доступ, включая active device, и сохраняет свои leases.

Обычная stream diagnostics panel читает admission один раз при открытии.
Подготовка WebRTC начинается только после явного нажатия. Смена профиля, устройства,
токена, logout, скрытие вкладки или unmount закрывают старую проверку.
Late HTTP responses не могут показать разрешение другого устройства/пользователя.
Профили ограничены host/public-STUN/server-granted TURN. IP и credentials в UI
не сохраняются. Точная граница этой коррекции на дату receipt: **source проверен
локально, ещё не установлен на UI639/API369**.

Focused local checks: backend 87 passed; latest panel subset 24 passed,
installer 27 passed; TypeScript, scoped ESLint/Ruff и scoped mypy прошли.
API schema экспортирована с repo-pinned Pydantic 2.9.2 в private validation target;
глобальное окружение не изменено. Один новый endpoint: 183 operations / 145 paths.
Hosted CI состояния относятся к SHA, указанному в JSON, и не переносятся на source
новой панели автоматически.

## Диск и открытые gates

Observer PID32064 и его epoch/source сверены. Замороженный срез: 171 complete
samples до 05:54:43 UTC; C: free delta −7 716 163 584 bytes. Docker VHDX allocation
234 731 077 632 bytes постоянен во всех этих samples. LDPlayer/Codex named files
объясняют только часть изменения. VSS/USN/kernel attribution недоступны; writer
остаётся UNKNOWN. Известные записи этой работы — APK/build output и bounded
fixtures — не исключены из общего расхода. Новая очистка не выполнялась.

Дальше нужны: actual browser-on-laptop ↔ PH030 echo/path; native authenticated
relay; media/control transport и ownership; per-tab viewer presence/handoff;
keyboard/IME/audio; correlated input-to-picture timing, reconnect и resource soak.
Ни один родительский enterprise backlog item этим receipt полностью не закрыт.
