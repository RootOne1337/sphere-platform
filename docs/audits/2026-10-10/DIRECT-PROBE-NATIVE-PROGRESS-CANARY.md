# Native setup и фактический UDP-путь: конечная проверка

10 октября 2026, итоговый срез 04:16 UTC / 09:16 UTC+5. Source
`161a23e97a323b2061aceaf56f84bc436cd90305`. Прямой канал пока не работает.
Подтверждены быстрый ответ APK, bounded native diagnostics и исходящие пакеты
на интерфейсе Android. Место потери обратного обмена ещё не установлено.

[Машинный receipt](DIRECT-PROBE-NATIVE-PROGRESS-CANARY.json) ·
[Текущий реестр](../../operations/STATUS-REGISTRY.json) ·
[Архитектура и следующие gates](../../design/BROWSER-DIRECT-TRANSPORT.md).

## Что изменилось по сравнению с предыдущим измерением

В canary934 браузер не получил answer до закрытия через 7,989 секунды.
Native stats тогда начинались только после answer, поэтому неизвестно, на каком
этапе остановилась подготовка. Этот отрицательный результат сохранён в
[прежнем receipt](DIRECT-PROBE-PUBLIC-STUN-CANARY.md).

Source161 добавил фиксированные этапы и stats до ответа. На трёх отдельных
process epochs APK последовательно прошёл factory, peer, remote description,
создание answer, local description и сбор ICE. Ответ отправлен за 392, 226 и
243 мс. Канал затем не открылся за прежние 12 секунд после ответа.
Прежний setup timeout не повторился; его причина не объявлена исправленной.

| Установка / PID APK | Answer от получения offer | Native reports | Последний ICE requests / responses | Итог |
| --- | --- | --- | --- | --- |
| 1 / 9745 | 392 мс | 13, включая 1 до answer | 246 / 0 | checking, DTLS new |
| 2 / 10871, первый peer | 226 мс | 13, включая 1 до answer | 242 / 0 | checking, DTLS new |
| 3 / 12342 | 243 мс | 13, включая 1 до answer | 241 / 0 | checking, DTLS new |

Во второй установке был ещё один явно запущенный peer: browser снова показал
connection deadline после answer. Native reader намеренно не объединял два
peer одного PID. Всего три установки и четыре явные проверки; не четыре
независимых process epochs и не четыре полных native traces.

Каждое из трёх native окон показало local candidates3, remote1, одну checking
пару, ноль успешных пар. Browser последнего окна: local5/remote2, две checking
пары, 177 requests/0 responses, DTLS connecting. Возраст последнего browser
среза 999 мс. Echo0, RTT и selected pair неизвестны. Счётчики разных сторон
и моментов измерения нельзя считать синхронным сквозным trace.

## Проверка пакетов на сокете APK

Финальная проверка использовала уже установленный root эмулятора и штатный
tcpdump. Порты host ICE candidates сначала сопоставлены с UID установленного
pilot package в `/proc/net/udp`; PID повторно проверен перед capture.
Фильтр ограничен одним подтверждённым сокетом APK на `wlan0`.

| Наблюдение в конечном окне | Число |
| --- | --- |
| Исходящие UDP к browser srflx candidate из offer | 237 |
| Входящие UDP от того же candidate | 0 |
| Исходящий STUN discovery / входящий ответ | 1 / 1 |
| Пакеты captured / received by filter / kernel dropped | 239 / 239 / 0 |
| Время между первым и последним пакетом | 11,823 с |

Это подтверждает выход пакетов с guest interface и получение STUN-ответа на
том же APK-owned socket. Это сильнее прежнего shell-only STUN prerequisite:
пакетный срез связан с UID и epoch нашего APK. Но он не показывает, дошли ли
пакеты до Windows/browser и где именно потерялись ответы. Отказ NAT hairpin,
маршрутизации, VPN, firewall или mDNS этим срезом не доказан.

Capture ограничен 14 секундами, 512 пакетами, snaplen96 и 128 KiB вывода;
promiscuous mode выключен. В памяти обработан вывод заголовков; сырые заголовки,
адреса, SDP, ICE credentials и packet payload в сохранённый отчёт не экспортированы.
Snaplen не означает, что в памяти tcpdump вообще не было байтов UDP payload.
245 строк stdout включали шесть строк служебного вывода; это 239 пакетов,
а не 245. Kernel dropped0 относится только к этому короткому capture.

Две предыдущие попытки сборщика во второй установке были невалидными:
первая остановилась на неверной передаче root-команды, вторая — на буквальной
кавычке в BPF. Они не доказывают отсутствие пакетов. Исправленный argv сначала
проверен с пустым фильтром без peer, затем принят только после реального
UID-filtered capture выше. Приватные отрицательные результаты сохранены.

## Source, APK и проверки

Четыре exact-source hosted CI завершились успешно: Android38020447092,
backend38020451358, frontend38020451363 и preview38020451353.
Отдельная локальная сборка дала 997 unit tests на каждый Dev/Enterprise variant,
0 failures/errors, 3 skipped. Оба lint: 0 errors, 38 warnings. Warnings не
объявлены отсутствующими. APK ZIP CRC, четыре JNI ABI, V2 signer и source root
проверены до установки; package/version/signer совпадают с исходным pilot.

APK SHA-256:
`27279d73bfe5de9998d0c5d2e7034850f0abdb38e86fa85c863c02b3d4ced7d2`.
Размер 57 655 284 B, версия1.2.49-dev/10249. Это диагностический artifact,
не stable1.3.0, не новая OTA и не обновление парка.

19 фиксированных progress events максимум на peer, каждый этап однократный;
terminal close/failure/expiry блокируют поздние success callbacks. Прежние
30s lease, 32 stats calls, один pending callback и mailbox32 сохранены.
Тесты проверили 10 000 повторных callback, terminal fencing и монотонное время.
Media/input и deadlines этим изменением не менялись.

Ранний build helper ошибочно выбрал старый export; тот результат не принят и
не установлен. В нём JBR21.0.9 C2 завершился с jvm.dll access violation при
компиляции SQLiteProgram. Причина не установлена: это не доказательство OOM
или неисправности SSD. После проверки фактического source root и нового output
сборка завершилась. Из 26 прочитанных System events в ограниченном окне
03:00→03:37UTC выбранных storage/WHEA ошибок не найдено; здоровье всего ПК
этим не доказано. Fatal logs остаются приватными.

## Возврат обычной установки

После каждой установки исходная APK восстановлена с SHA-256
`6b177bcbac3bb319597630f34f88956bc79a6e0e3261508c2fe09708b393b013`.
Данные приложения не очищались. Три отдельных шестиминутных guardian завершились
`verified_manual_cleanup`; peer не продлевал 30s lease.

Итоговая обычная установка: UI639/API369. UI container2109cf7c сохранён;
API containerfe9fb8f3, epoch04:12:56UTC, тот же image/source. Gate выключен,
allowlist пуст; probe до JWT возвращает4003/direct_probe_disabled.
На обоих адресах ready/build/device проверки прошли, PH011 online.
Schema, OTA digest и 45 соседних контейнеров сохранены при каждой замене API.
Временные loopback3016/3017 остановлены, проверочные вкладки закрыты.

После финального возврата обычный viewer показал local11/public2 decoded/drawn
frames, invalid/decode/render errors0. Это конечная проверка кадров. Открытие
embedded stream сначала включает default control, затем выбран view-only;
касания, клавиши и свайпы не отправлялись. Public opening notice server_rejected
сохранён, а Android capture telemetry местами ещё not_streaming. Эти сигналы
не скрыты и не являются приёмкой управления, FPS, latency или resource soak.
DOM и screenshots отказа сохранены до cleanup, файлы приватные; в receipt
только fingerprints и редактированная сводка.

## Ресурсный срез и остаток

Один limited observer PID32064/epoch00:14:44UTC продолжает окно до12:34UTC.
Заморожен prefix120 complete samples до04:12:43UTC: свободное C:
46 521 065 472→39 716 073 472 B, изменение−6 804 992 000 B.
Docker VHDX allocation234 731 077 632 B постоянен во всех этих samples.
Два LDPlayer VMDK выросли на2 359 296/159 318 016 B, Codex SQLite на25 673 728 B.
Это не покрывает весь расход C:. VSS/USN/kernel attribution в этом
unprivileged окне недоступны; writer и причина общей потери неизвестны.
Процесс, epoch и complete samples проверены; будущая непрерывность не гарантируется.

Следующий сетевой шаг — сопоставить APK-owned packet window с ограниченным
наблюдением стороны Windows/browser, затем отдельно сравнить authenticated
relay profile. Нельзя исправлять неизвестный route failure увеличением timeout
или отключением firewall/VPN. Принять DataChannel/RTT нужно до media/input,
далее нужны reconnect/ownership/network/resource gates.

Product9 принято/41 открыт, legacy7 незакрытых. Новых product items этим
диагностическим этапом не закрыто; stable APK1.3 остаётся NO-GO.
