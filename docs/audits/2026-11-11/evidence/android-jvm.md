# Android JVM — локальный прогон от 11 ноября 2026 года

Windows, JDK 17.0.17, Gradle wrapper 8.9, Android SDK с платформой API 35. Исходники `android/` соответствуют `94cf7c3a2a50bbc8197737f5cf666e0e2c8ddec3`. Обычные debug-варианты без включения canary-профилей. Команда из `android/`, с `ANDROID_HOME` и `ANDROID_SDK_ROOT`, указывающими на установленный локальный SDK.

```powershell
.\gradlew.bat :app:testEnterpriseDebugUnitTest :app:testDevDebugUnitTest :awg-client:testDebugUnitTest --console=plain --no-daemon --max-workers=2
```

| Gradle task | Наборы XML | Всего | Прошло | Ошибки / failures | Пропуски |
| --- | ---: | ---: | ---: | ---: | ---: |
| `:app:testEnterpriseDebugUnitTest` | 122 | 1296 | 1293 | 0 / 0 | 3 |
| `:app:testDevDebugUnitTest` | 122 | 1296 | 1293 | 0 / 0 | 3 |
| `:awg-client:testDebugUnitTest` | — | — | — | `NO-SOURCE` | — |

Агрегаты получены суммированием атрибутов `tests`, `failures`, `errors`, `skipped` файлов `TEST-*.xml` по каждому каталогу `android/app/build/test-results/<task>`. В каждом варианте пропущены одинаковые случаи.

- `ScreenshotFileStoreTest` — `store directory symlink is rejected before any write`, `owned-looking symlink blocks capture without deleting external target`. Windows не предоставил привилегию создания симлинков.
- `ConfigRecoveryTest` — `public discovery of baked route retains locally provisioned enrollment credential`. Тест выполняется при заданных build-time URL и ключе discovery.

Завершение Gradle, код 0.

```text
1 problem was found storing the configuration cache.
- Task `:awg-sdk:verifyUpstream` of type `org.gradle.api.DefaultTask`: cannot serialize Gradle script object references as these are not supported with the configuration cache.

BUILD SUCCESSFUL in 11m 46s
94 actionable tasks: 61 executed, 33 up-to-date
Configuration cache entry discarded with 1 problem.
```

Проверка `adb devices -l` показала пустой список. Установка APK, Android instrumentation, реальный ввод, запуск фоновых Activity, проверка транспорта VPN и MediaProjection требуют стенда с Android.
