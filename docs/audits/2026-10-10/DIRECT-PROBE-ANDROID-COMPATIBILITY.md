# Native ICE diagnostics: исправление совместимости Android

Дата: 10 октября 2026, UTC+5. Это исправление исходников и запись отказа CI;
обновление APK на устройствах в этом этапе не выполнялось.
[Действующие работы](../../operations/WORK-STATUS.md) ·
[Машинное доказательство](DIRECT-PROBE-ANDROID-COMPATIBILITY.json).

## Обнаруженный дефект

В source `0abe15ce` reducer новых ICE counters использовал
`BigInteger.longValueExact()`. JVM-тесты проходили, но Android Lint в
[exact-source CI](https://github.com/RootOne1337/sphere-platform/actions/runs/37998676869)
обнаружил `NewApi`: метод требует API 31, тогда как minimum SDK — 26.
Проверочный PH011 фактически работает на Android 9 / API 28.

Это дефект новой диагностической сборки. Она **не устанавливалась** и не
публиковалась в OTA; дефект не объясняет уже наблюдавшиеся задержки рабочего
viewer или предыдущий отказ ICE. Локальные JVM-проверки не заменяют Android
API compatibility gate. Предыдущий
[source/test receipt](DIRECT-PROBE-NATIVE-NETWORK-SOURCE.md) сохранён как
исторический результат; более поздний отказ CI записан здесь.

## Исправление

[Reducer](../../../../android/app/src/main/kotlin/com/sphereplatform/agent/direct/DirectProbeNetwork.kt)
проверяет неотрицательный знак и `bitLength <= 63` перед преобразованием в
`Long`. В допустимом диапазоне преобразование точное; отрицательные значения,
выход за `Long.MAX_VALUE` и переполнение суммы по-прежнему дают `null`.
Minimum SDK, manifest и исключения Lint не менялись.

Новая [регрессия](../../../../android/app/src/test/kotlin/com/sphereplatform/agent/direct/DirectProbeNetworkTest.kt)
проверяет `Long.MAX_VALUE`, следующее число, `Long.MIN_VALUE` и минус один.
Это JVM-проверка числового контракта. Совместимость Android API отдельно
проверена Lint; реальное выполнение нового JNI callback ещё не принято.

## Проверки исправления

Запуск с `SPHERE_DIRECT_TRANSPORT_CANARY=true`, offline, два Gradle worker,
heap 1536 MiB, `--no-daemon`:

| Проверка | Результат |
| --- | --- |
| `:app:lintDevDebug` | 0 errors, 37 warnings |
| `:app:testDevDebugUnitTest` | 990 tests, 85 suites, 0 failures/errors, 3 skipped |
| `:app:testEnterpriseDebugUnitTest` | 990 tests, 85 suites, 0 failures/errors, 3 skipped |
| `DirectProbeNetworkTest`, оба профиля | 6 tests, 0 failures/errors/skips |
| Gradle | BUILD SUCCESSFUL, 5m 1s |

Оба профиля в **этом** запуске включали canary source set. Ранее ordinary
Enterprise проверялся на `0abe15ce`; это отдельный исторический результат.
37 предупреждений Lint не скрыты и не равны новым ошибкам совместимости.
Свежие XML, Lint report и build log сохранены локально; в receipt записаны
их хеши. Hosted CI нового исправления и signed artifact admission остаются
обязательными перед установкой.

## Состояние после отказа кандидата

На срезе 9 октября 22:35:50 UTC рабочие UI/API оставались `369654a0`.
Исходный APK PH011 `1.2.49-dev / 10249` сохранён; его SHA-256 проверен.
API probe выключен, allowlist пуст. Временные loopback listeners 3016/3017
остановлены, диагностическая вкладка закрыта. APK `0abe15ce` отвергнут
до установки, OTA не менялась.

Следующий эксперимент должен быть конечным: один PH011, согласованные browser
и native ICE counters, затем возврат исходного APK и отключение probe.
Успешный answer не означает успешную ICE-пару или рабочий DataChannel.
Последний реальный browser результат остаётся 177 checks / 0 responses;
причина сетевого отказа, live RTT и public idle ACK reliability открыты.
Product 9 accepted / 41 open и legacy 7 unclosed не изменены.
