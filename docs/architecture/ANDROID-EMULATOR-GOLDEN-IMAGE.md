# Golden image и переносимое клонирование Android-эмуляторов

**Статус: архитектурный аудит и обязательные gates перед Fleet32.**
**Проверено: 24 сентября 2026.**

[Документация](../README.md) · [Clone binding v2 и evidence](../audits/2026-09-20/CLONE-BINDING-V2.md) ·
[Fleet32 preflight](../audits/2026-09-20/FLEET32-PREFLIGHT.md) ·
[Remote pilot](../operations/REMOTE-PILOT.md) ·
[Boot recovery](../audits/2026-09-05/ANDROID-BOOT-RECOVERY.md) ·
[Разрешения root и unattended](../audits/2026-09-05/ANDROID-UNATTENDED-CAPABILITIES.md)

> [!IMPORTANT]
> Можно и нужно подготовить **запускаемый master**: установить Sphere и целевое
> приложение, включить root, один раз пройти доступные экраны настройки и
> разрешения. При клонировании копируется Android-состояние, поэтому вместе с ним
> могут копироваться device credentials и настройки приложений. Каждому клону
> требуется отдельная стабильная identity до первого запроса со скопированными
> device credentials. Первичная регистрация использует отдельный enrollment key. Это
> требование относится к любому гипервизору. Базовая установка Sphere не должна
> требовать Windows/Linux сервиса на станции: APK самостоятельно подключается к
> серверу по исходящим TLS/WSS-соединениям. Управление гипервизором остаётся
> необязательной интеграцией, а не условием подключения.

## 1. Решение для текущего проекта

Master с уже запущенным и зарегистрированным APK не запрещён. Текущий APK v2
сверяет сохранённый binding с ro.boot.serialno / ro.serialno и перед командным
WebSocket повторно регистрируется, если VM serial изменился. Этот путь даёт отдельные
карточки без переустановки, **если гипервизор выдаёт клонам разные стабильные serial**.

Аудит обнаружил неполное применение этой защиты: при старте процесса одновременно
планируются OTA-check и upload логов. До исправления эти workers могли обновить
refresh token или обратиться к API под скопированными credentials, не дожидаясь
clone rebind. Общий HTTP-интерцептор также добавлял старый bearer к первичному
запросу регистрации, хотя этот endpoint должен принимать только enrollment key.
Теперь registration guard применяется до OTA-каталога, скачивания APK и log upload,
а регистрационный POST исключён из автоматического добавления device bearer. Ошибка
rebind оставляет старые credentials в локальном хранилище только для следующей
попытки; запросы не используют их до успешного подтверждения новой binding.
Регрессии проверяют отсутствие обращения при неудачном rebind и отсутствие старого
bearer в enrollment-запросе.

Эта защита **не способна разделить два клона с одинаковым serial и одинаковым
состоянием приложения**. В таком случае текущая проверка сочтёт второй запуск тем же
устройством. Поэтому для Fleet32 обязательны две независимые проверки:

1. получить разные стабильные identity на каждом экземпляре и после перезагрузки;
2. убедиться, что все API consumers ждут rebind перед использованием скопированных
   credentials.

На двух доступных здесь LDPlayer 9 / Android 9 serial различаются, а ANDROID_ID
совпадает. Это локальная read-only проверка **2 из 2**, без установки, перезапуска
или изменения настроек. Она подтверждает выбор источника v2 для этой пары, но не
поведение Clone на 20 удалённых VM. Их serial, точный образ и фактический APK
не были прочитаны в этой проверке.

## 2. Что копирует master, а что ещё предстоит доказать

LDPlayer документирует, что Clone player копирует установленные приложения.
Следовательно, нельзя считать, что клон начинает работу как чистая установка.
В зависимости от того, какие разделы копирует конкретная версия LDPlayer, в новый
экземпляр могут попасть:

- APK Sphere, его SharedPreferences, локальные файлы и сохранённые access/refresh
  credentials;
- APK целевой игры, локальный аккаунт, кэш, идентификаторы сессии и загруженные
  ресурсы игры;
- системные настройки и разрешения Android, AppOps, уведомления и настройки root;
- снимок запуска или данные восстановления, которые содержат процессное состояние.

Первый пункт подтверждён архитектурно для Android-приложения: его приватные данные
содержат token store. Но точное содержимое clone для каждой версии LDPlayer должно
быть проверено на disposable canary. Официальное описание клонирования не обещает,
что каждое runtime-разрешение или внутреннее системное состояние переносится
одинаково во всех Android images.

Нельзя путать Sphere device identity с аккаунтом игры. Уникальная карточка Sphere
не очищает и не переиздаёт account/session data целевого приложения. Если игра
сохраняет собственный login/device token в /data, копия master может запустить
один и тот же игровой аккаунт на клонах. Это отдельный сценарий и он зависит от
самой игры; до массового копирования нужно решить, предполагается ли общий аккаунт,
чистый первый запуск или индивидуальный аккаунт на каждый эмулятор.

## 3. Почему одного первого сетевого подключения недостаточно

Backend может выдать device_id и tokens при первом запросе, но он должен отличить
клон от исходного экземпляра **до** выдачи стабильной карточки. Если два клиента
предъявляют один и тот же token, fingerprint, VM serial, binding и скопированное
локальное состояние, server-side алгоритм видит одну и ту же identity. Общий
внешний IP станции, порядок принятия TCP-соединений и случайный WebSocket nonce
не решают повторное узнавание после reconnect: IP может быть общим за NAT или
измениться, а nonce создаётся заново для каждого соединения.

Практическое правило для базового продукта: Android runtime должен предоставить
устойчивый сигнал, который отличается у клонов. Для текущего APK таким сигналом на
эмуляторах служит VM serial, если он доступен и уникален; у физического устройства
используется Android-native app/device identity. Адрес сервера и enrollment key
находят backend и разрешают регистрацию, но сами по себе не доказывают, что два
одинаковых Android-образа — разные VM.

Если runtime копирует один и тот же serial и всё локальное состояние приложения,
backend не может вычислить скрытый факт «это другая VM» из сети. Новый случайный ID
на каждый процесс потерял бы стабильность при перезапуске. В этом случае продукт
должен показать identity collision и не объединять устройства молча. Опциональная
интеграция с гипервизором возможна для специальных сред, но не является требованием
обычной установки Sphere.

APK, enrollment protocol и backend остаются общими для Android phone и Android
emulator. Поддержка другого эмулятора определяется тем, отдаёт ли его Android image
доступную APK стабильную и уникальную per-instance identity и проходит ли она те же
clone/reboot canary-тесты; отдельный station service по умолчанию не нужен.

## 4. Целевая переносимая схема

### 4.1 Контракт identity

Для одного Android instance используются:

- `instance_binding_version`: версия алгоритма, которой APK доказывает identity;
- `instance_binding`: digest стабильного Android-native proof, не сырой serial;
- `device_id`: логическая запись, выданная backend; сам по себе это не источник
  уникальности клиента;
- `boot_id`: новый ID при каждом Android boot, только для корреляции событий;
- `session_id`: новый ID каждого WebSocket/capture-сеанса, только для диагностики;
- необязательный `station_id`: диагностический атрибут, если конкретный оператор
  позже подключил интеграцию с гипервизором.

Identity source не должен быть MAC, IP, ADB transport ID, портом, именем эмулятора,
UI index или значением игры. Backend хранит digest и provenance, а не сырые serial.
Повторная регистрация одной binding идемпотентна; разные подтверждённые Android
proof в одной организации получают разные device IDs.

### 4.2 Поддержка старых и новых гипервизоров

Порядок Android-native источников должен быть явным, версионируемым и покрытым
тестами:

1. **Эмулятор:** доступный APK стабильный VM serial (`ro.boot.serialno`, затем
   `ro.serialno`) — только для проверенного сочетания эмулятора, версии и образа.
   Это текущий v2 путь.
2. **Физический Android:** допустимый app-scoped/device-scoped Android identifier;
   его устойчивость проверяется после перезапуска и переустановки в соответствии с
   выбранной моделью. Непривилегированное приложение не должно рассчитывать на
   доступ к запрещённым hardware serial.
3. **App GUID или Keystore key:** полезны как дополнительный app-instance proof,
   если они созданы после финального клонирования. Значения, созданные в уже
   запущенном master, могут попасть в clone вместе с app/Keystore state, поэтому
   сами по себе не решают текущий golden-image сценарий.

Android определяет `ANDROID_ID` как scoped по signing key, user и устройству на
Android 8+, но это свойство платформы не обещает уникальность snapshot-клонов; в
нашей локальной паре значения уже совпали. Android рекомендует app-scoped GUID/FID
для обычного учёта установки, но GUID, созданный до клонирования, копируется вместе с
состоянием приложения. Android Keystore помогает защитить ключевой материал;
hardware-backed storage зависит от конкретного устройства и не гарантировано на
эмуляторе. Это дополнительные proof-сигналы, а не автоматический способ узнать, что
VM была клонирована. См. официальные [Android identifier best practices](https://developer.android.com/identity/user-data-ids),
[`ANDROID_ID` reference](https://developer.android.com/reference/android/provider/Settings.Secure#ANDROID_ID)
и [Android Keystore](https://developer.android.com/privacy-and-security/keystore).

Если proof отсутствует или повторяется, приложение не должно подменять его MAC,
IP или GUID из master. Оно должно сохранить понятный диагностический статус и не
создавать ложные записи. Серверный endpoint discovery остаётся отдельным шагом:
он возвращает адреса backend, но не является поставщиком Android identity.

Никакой host seed transport не входит в базовый продукт и не реализован. Если
специальному гипервизору он понадобится как дополнительная опция, это отдельный
ADR. Основная acceptance matrix должна пройти без запуска сервисов на Windows/Linux.

### 4.3 Опциональная интеграция с гипервизором

Управление гипервизором не входит в основной путь подключения Android APK. Если
в будущем понадобится автоматизированный inventory или batch-клонирование,
интеграцию следует вынести в отдельный необязательный компонент. Он может сообщать
серверу имя VM и состояние host, но не должен становиться обязательным для
подключения, переподключения, стрима, команд или OTA.

## 5. LDPlayer как первый проверяемый Android runtime

Текущая цель — LDPlayer 9, Android 9 64-bit. Проверяются именно Android-сигналы,
которые читает APK, а не только список окон Multi-Instance Manager. Обычная работа
не требует установленного на Windows агента или запущенного `ldconsole` сервиса.

Официальная справка LDPlayer описывает CLI для диагностики и управления инстансами,
но не гарантирует, что Clone получает новый `ro.boot.serialno`/`ro.serialno`, что
Android ID будет изменён и сохранится после cold boot или что runtime-разрешения и
MediaProjection-согласие копируются. В доступной локальной паре serial различался,
ANDROID_ID совпал. Это не подтверждает поведение 20 удалённых клонов.

Canary-проверка без массового изменения должна пройти три клона от master:

1. сохранить исходный master и не удалять текущие VM;
2. создать три временных клона штатными средствами LDPlayer;
3. запустить APK обычным способом и проверить в редактируемом диагностическом
   отчёте только hash binding, registration outcome и выданный device_id;
4. подтвердить три разные карточки, одновременные WebSocket-сессии без вытеснения,
   OTA metadata после регистрации и первый реальный stream frame;
5. перезапустить каждый clone и убедиться, что device_id остаётся стабильным;
6. отдельно проверить Android permission/AppOps и повторное открытие MediaProjection;
7. только после pass расширять волну 3 → 5 → 10 → 20 → 32.

Если serial у клонов повторяется, текущий v2 APK видит их как один instance, потому
что binding совпадает. Это блокирующий результат: не лечить его переустановкой APK,
сменой display name или записью Android ID, пока не доказано, что выбранный сигнал
действительно изменил identity, которую читает APK.

## 6. Поддержка другого Android-эмулятора

APK и backend остаются платформенно-нейтральными: отдельный Windows/Linux процесс не
нужен. Для телефона используется поддерживаемый Android identifier; для эмулятора —
доступная APK стабильная identity, которую выдаёт конкретная Android image. Новый
эмулятор становится поддерживаемым после той же проверки: чистый install, master
setup/permissions, clone, уникальность binding, устойчивость после reboot, connect,
OTA, stream first frame и восстановление сети.

Если новая Android image клонирует все доступные APK признаки вместе с сохранённым
app/Keystore state, на ней пока нельзя обещать автоматическое разделение клонов.
Строгий режим должен показать оператору `identity_conflict` с объяснением и сохранить
безопасность данных; универсальность достигается сертификацией Android runtime-ов, а
не наличием обязательного инструмента управления на каждом host.

## 7. Критический порядок старта APK

При создании процесса нельзя запускать ни один background consumer, который обновляет
или отправляет скопированные credentials до успешного clone rebind. Требуемый порядок:

- process start;
- load config and identity provider;
- compare saved binding/version with current per-instance binding;
- if different: discover management route and register current instance;
- atomically save server ACK + new device ID + tokens + binding/version;
- permit WebSocket, token refresh, OTA catalog/download, log upload;
- start normal command/capture work.

**Подтверждено в source до исправления:** SphereApp.onCreate() планировал
LogUploadWorker и UpdateCheckWorker при каждом старте. Только WebSocket имел
InstanceRegistrationGuard. UpdateCheckWorker вызывал getFreshToken() до gate,
LogUploadWorker также сначала обновлял token и собирал device ID; это позволяло
попытку refresh/upload до rebind. Скопированный refresh token, общий на клонах,
добавлял риск конкурентной ротации.

**Исправлено в этой ветке:** OTA catalog worker теперь проверяет регистрацию до
refresh или HTTP; OTA service повторно проверяет непосредственно перед download;
log upload worker делает rebind до refresh, чтения логов и HTTP. Ошибка rebind
возвращает retry, старые tokens не очищаются, а до успешного gate не отправляются.
Отмена log worker пробрасывает CancellationException и не подменяется retry.

Все будущие HTTP consumers device credentials должны использовать тот же guard.
Code review gate: поиск getFreshToken(, getToken(, Authorization, X-API-Key и
X-Device-Id в Android source; для каждого caller должен быть доказан guard либо
явно описано, почему caller не относится к зарегистрированной VM-сессии.

## 8. Master, enrollment и безопасный rollout

Для текущего v2 serial binding допустимы такие варианты:

### Master уже зарегистрирован

Можно создать clones, если предварительный canary доказал уникальные serial. Каждый
новый serial вызовет серверную регистрацию до WebSocket, OTA или загрузки логов.
После успешного ACK APK сохраняет новую карточку и credentials, а затем может
переподключиться самостоятельно. Повторный запуск той же VM сохраняет её device ID.

### Master не зарегистрирован или serial одинаков

Все клоны должны иметь identity, изменённую после copy до первого сетевого
действия. Per-instance seed должен назначаться автоматизированным adapter-ом и
проверяться самим APK. Пока такая provisioning реализация не сделана для точного
target, текущий строгий v2 APK безопасно откажется регистрировать missing serial,
но не сможет разделить одинаковый serial.

### Backend и APK

Backend с binding version должен быть развернут раньше APK. Дальше — один canary,
проверка версии ACK и отдельной карточки, затем 3/5/10/20/32. Не надо удалять
старые VM или общую карточку до инвентаризации устройства, версии, stream и очередей.
OTA применяется после корректной регистрации и правильной записи platform, flavor,
version_code; изменение ID не публикует APK и не чинит отсутствующую запись в OTA
catalog. Перед массовым rollout отдельно проверить signer, application ID, artifact
SHA-256 и обратимость каталога.

## 9. Root, grants и стрим экрана

Настроить master один раз всё равно полезно: включить root, установить целевую игру,
установить APK и разрешить статические Android capabilities, если они доступны в
этой image. Но приёмка проверяет каждую категорию отдельно:

| Capability | Что может переноситься образом | Что проверить |
| --- | --- | --- |
| Root / su daemon | Настройки emulator image | su -c id, повтор после cold boot, без интерактивного запроса |
| Runtime permission приложения | Android package/system state | dumpsys package, вызов реальной функции, поведение на clone |
| AppOps, включая PROJECT_MEDIA | Системная настройка Android; не считать доказанным | cmd appops get, реальный запуск ScreenCapture и новый кадр |
| Уведомления / foreground service | Может зависеть от Android version и образа | service state, системное уведомление, recovery после reboot |
| MediaProjection session token | Короткоживущая OS-issued session | каждый новый createScreenCaptureIntent() и фактический VirtualDisplay |

Sphere сейчас может установить PROJECT_MEDIA AppOp через root, но код всё равно
вызывает createScreenCaptureIntent() и получает MediaProjection token из результата
системного activity. AppOp не равен токену сессии. Официальная Android документация
требует согласие на каждую новую сессию и ограничивает повторное использование
токена; Android 14 усиливает одноразовость. Текущий target LDPlayer Android 9 нужно
проверять непосредственно: наличие иконки захвата или AppOp allow не доказывает
поступление кадров. На физических устройствах нельзя обещать скрытый/универсальный
screen capture без пользовательского consent.

Чтобы не нажимать одно и то же вручную на каждом clone, station automation должна
либо проверить, что permission state безопасно переживает копию, либо иметь
поддерживаемый Android/OEM путь grant-а. Если это невозможно, один системный prompt
на clone остаётся явным ограничением. Не маскировать prompt автоматическим tap/script:
это хрупко, зависит от языка/окна и не эквивалентно системному grant.

## 10. OTA и обновление без ручной установки на каждый клон

У каждого клона должен быть уникальный device_id, но APK package и signer остаются
одинаковыми. OTA каталог может назначить тот же релиз всем VM нужного platform и
flavor, если version_code больше установленного. Для безопасного обновления важно,
чтобы каждый clone сначала прошёл identity guard; затем каждый независимо проверит
каталог. APK build сам по себе не означает, что релиз опубликован.

До первого OTA rollout проверить canary:

- clone уже зарегистрирован отдельной карточкой;
- установленный package и подпись совпадают с OTA;
- catalog содержит ожидаемые platform, flavor, version_code, URL и hash;
- один clone скачал и проверил тот же artifact, остальные не увидели несовместимый
  flavor или downgrade;
- ошибка сети возвращает retry без удаления credentials или частичного APK;
- установка заменяет APK без потери per-instance binding.

## 11. Наблюдаемость и forensic-доказательства

Каждый жизненный цикл должен коррелироваться по station_id, instance_id (redacted
digest), device_id, boot_id, session_id, task_id и UTC time. Сырые Android serial,
bearer/refresh tokens, enrollment keys, game credentials и полный URL с секретными
query parameters запрещены в диагностических events.

На карточке устройства и в incident bundle нужны:

- host adapter, host instance name, Android release/API и app version/code;
- источник identity и статус uniqueness check: verified, duplicate, missing;
- последняя попытка rebind: время, duration, outcome, HTTP class и retry count;
- текущие device_id и binding version; token никогда не показывать;
- boot/reconnect timeline: process start, route discovery, registration ACK, WS auth,
  heartbeat, disconnect reason и restore duration;
- stream lifecycle: consent/AppOp outcome, projection start/stop, encoder ready,
  SPS/PPS, IDR, backend ingress, viewer decode, first-frame latency и last-frame age;
- OTA: catalog version, artifact hash, download/verify/install outcome и installed
  version, без signed download token;
- bounded logs и crash buffer до/после теста, с redaction и privacy budget.

Инцидентный отчёт должен давать вывод по каждому клону, а не общий «22 устройства
online»: host VM → observed binding → backend device → last heartbeat → stream
freshness → APK version → last error. UI должен явно отличать online от
streaming/current frame received.

## 12. Матрица тестов до 32 эмуляторов

| Stage | Проверка | Pass condition |
| --- | --- | --- |
| 1 | Один свежий clone, registration, websocket, экран | Одна карточка, новый кадр, zero copied-device-token traffic; enrollment использует отдельный key |
| 2 | Ещё два clone от того же master | 3 distinct bindings + 3 stable device IDs |
| 3 | Restart each clone twice | Те же три IDs, no duplicate records/session eviction |
| 4 | Clone с искусственно одинаковым serial | Batch отказывает или seed-path создаёт разные IDs; silent merge запрещён |
| 5 | Identity отсутствует / config endpoint недоступен | Нет запросов со старым device token; виден точный retry reason |
| 6 | Internet outage отдельно на station и server | Автоповтор после recovery, registration идемпотентна |
| 7 | Короткий OTA rollout на canary | Artifact/signature/hash/version подтверждены; rollback понятен |
| 8 | Screen capture/permission restart | Новый session token получен допустимым путём, кадр декодируется |
| 9 | 5 → 10 → 20 → 32 | Каждая ступень проходит identity, stream, memory, CPU, Redis и reconnect SLO |

Для каждого теста сохранить baseline и after snapshots, per-instance counts, unique
binding count, unique device count, identity collisions, registration ACKs, refresh
outcomes, WebSocket evictions, crash delta и first-frame timing. running — не pass.

## 13. Риски и нерешённые решения

| Приоритет | Риск / неизвестное | Почему важно | Требуемое доказательство / работа |
| --- | --- | --- | --- |
| **P0** | Удалённые LDPlayer clones могут иметь одинаковый serial | v2 не разделит одинаковые bindings | Снять identity на 3 canary; collision означает NO-GO до Android-only решения или выбора совместимого image |
| **P0** | Golden image копирует device refresh credentials | token rotation и duplicate session между клонами | Rebind barrier реализован для WS/OTA/log; regressions есть, remote canary остаётся open |
| **P0** | Cloned game private data может содержать общий аккаунт | Sphere identity не изолирует стороннее app state | Проверить игру отдельно по продуктовым правилам |
| **P1** | Permission/AppOps переносимость неизвестна | Screen stream может требовать prompt | Android 9 LDPlayer clone proof; Android 14+ отдельная политика |
| **P1** | OTA version/flavor/signer misalignment | Клоны остаются без обновления или получают неверный APK | Canary metadata/hash/signature/install evidence |
| **P1** | Backend не имеет доказанного collision recovery для одной active binding | Новый WS может вытеснить текущий, если две VM предъявят один proof | Проверить canary и quarantine collisions, без молчаливого rebind |
| **P2** | Перенос на другой emulator не проверен | Android image может иначе отдавать native identity | Повторить install/clone/reboot/network/stream acceptance suite; station service не требуется |

До закрытия P0 массовое клонирование остаётся **NO-GO**. Локальные 2 serial, CI,
source APK build и backend concurrency test не являются доказательством уникальности
20 удалённых клонов или успешного video path.

## 14. Что изменено в этом аудите

- Добавлены clone-rebind gates перед OTA metadata request, OTA download и log upload.
- Добавлены regression tests, которые до исправления падали: в них clone мог
  отправить старый token/ID; теперь запрос отсутствует, пока guard не вернёт успех.
- Сетевой interceptor до фикса добавлял bearer master-инстанса в POST
  `/api/v1/devices/register`. Красный regression test это воспроизвёл; после фикса
  enrollment уходит без `Authorization`, используя enrollment `X-API-Key`.
- При ошибке log upload worker теперь также сохраняет coroutine cancellation.
- Полные Android unit suites после изменений: dev **627/627**, enterprise
  **627/627**, ошибок нет, один существующий skip в enterprise; `assembleDevDebug` и
  `assembleEnterpriseDebug` прошли. Получены локальные debug builds 1.2.13-dev/10213
  и 1.2.13/10213. Они используют debug signing и не загружены в OTA; это не release
  APK для массовой установки.
- Прочитаны два работающих локальных LDPlayer 9 Android 9 инстанса без изменения
  состояния: VM serial 2/2 distinct, Android ID 2/2 equal.
- Сверены официальные LDPlayer CLI/Multi-Instance docs и Android MediaProjection
  rules; ссылки перечислены ниже.

Не изменялись и не проверялись на этом шаге: удалённые LDPlayer instance state,
серверный deployment, OTA catalog, права/гранты двух работающих VM, подпись remote
APK, фактический clone, удалённый WebSocket, stream или game account state. Этот
документ — архитектурное решение и checklist, не отчёт о прохождении этих gates.

## 15. Источники

1. LDPlayer Support, [Command Line Interface](https://www.ldplayer.net/support/introduction-to-ldplayer-command-line-interface.html):
   команда CLI, copy, modify, runapp, getprop, list2.
2. LDPlayer, [Multi-Instance Manager](https://www.ldplayer.online/support/introduction-to-ldmultiplayer.html):
   clone копирует установленные приложения, batch/optimization и backup/restore.
3. Android Developers, [Media projection](https://developer.android.com/media/grow/media-projection):
   получение токена, consent на сессию, ограничения повторного использования,
   завершение и освобождение ресурсов.
4. Android Developers, [Start the emulator from the command line](https://developer.android.com/studio/run/emulator-commandline):
   запуск AVD, выбор портов, userdata path и различия host emulator controls.
5. First-hand user report, [LDPlayer cloned instances and copied game session](https://www.reddit.com/r/LDPlayerEmulator/comments/1gyhyvr/):
   анекдотическое свидетельство о возможной копии game state; не используется как
   доказательство реализации Sphere или гарантий LDPlayer.

Внешние отчёты сообщества используются только как сигнал о типе возможной проблемы.
Технические гарантии берутся из официальной документации и проверяются на точной
версии LDPlayer/Android, установленной на станции.
