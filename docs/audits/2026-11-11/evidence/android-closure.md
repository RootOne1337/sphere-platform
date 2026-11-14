# Android — проверка артефактов и доступности устройства

11 ноября 2026 года `adb devices -l` с ADB 35.0.2 вернул только `List of devices attached`. Готовность установленного APK, системные диалоги, повторное подключение, OTA и нативный VPN на этом проходе остаются без наблюдения на устройстве.

## Привязка к исходникам

На момент проверки HEAD был `38b342de0feb5dd45ac901c08f0e37467afffec7`. Каталог `android/` у HEAD, исходного среза аудита `94cf7c3a2a50bbc8197737f5cf666e0e2c8ddec3` и зафиксированного исходного коммита APK `ef69ee25342c9f59ed6fd137f03e38295a38b1fa` имеет один Git tree `22e5b8f6073bb5947259fa51bb44a04c5aaf8d67`. `git status --short -- android` ничего не вывел. В пределах этих ревизий `git diff --name-only` по `android/`, `ci-android.yml` и `package-android-pilot.yml` пустой. Это позволяет сопоставить APK и исходники Android. Привязка не охватывает поведение изменившихся внешних сервисов и не заменяет проверку параметров конкретной release-сборки.

## Два локальных APK версии 10292

| Артефакт | Package / version | SHA-256 |
| --- | --- | --- |
| `SphereAgent-app-vpn-canary-1.2.92-dev-ef69ee2.apk` | `com.sphereplatform.agent.pilot.debug` / `1.2.92-dev` | `a124f61920f09aa6ba5ae7becb14dcd267d05ad6365556478cd968a39c07e0b9` |
| `app-enterprise-debug.apk` из того же сохранённого каталога сборки `teaching92-apk-ef69ee2-resolved-metadata` | `com.sphereplatform.agent.debug` / `1.2.92` | `95ef5e3d4a39ca7c9b383fd4ace2b4073f74108ffa2a3d833d1314aacf9b0509` |

У Dev APK полученный SHA совпал с локальным build sidecar, файлом `app-dev-debug.apk` из указанной в sidecar сборки, локальной копией OTA-объекта и опубликованным в репозитории историческим отчётом. EnterpriseDebug найден в том же каталоге сохранённой сборки. Для него SHA измерен заново, независимого sidecar с исходной ревизией и SHA в проверенном наборе нет. [История Dev APK](../../2026-10-26/PH011-APK92-GPU-PLANAR-CAPTURE.md#L33-L35).

Для обоих APK `apksigner verify --verbose --print-certs`, `aapt2 dump badging` и `aapt2 dump xmltree --file AndroidManifest.xml` из Android SDK Build Tools 35.0.0 завершились с кодом 0. Проверен один подписант и APK Signature Scheme v2. SHA-256 сертификата совпадает между APK и метаданными Dev canary: `3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`. Оба манифеста объявляют `debuggable=true`, `minSdk=26`, `targetSdk=35`, `AppScopedVpnService` включён в отдельном процессе `:vpn`. `aapt2` сообщает native-код для `arm64-v8a`, `armeabi-v7a`, `x86`, `x86_64`. Это перечень ABI в APK, загрузка отдельных библиотек на устройстве остаётся непроверенной. Сборочный скрипт относит app-scoped VPN и GPU planar к debug-canary. [Ограничения сборки](../../../../android/app/build.gradle.kts#L75-L98).

## Граница release-приёмки

Проверены локальные каталоги сборок и пилотных артефактов. Из 295 найденных файлов пять имели дату изменения от начала сборки 1.2.92. Это три копии одного Dev APK, EnterpriseDebug из того же каталога и небольшой unsigned APK тестового приёмника. Среди файлов в проверенной области отсутствовали AAB и APK в `release`-каталогах. Текущие `output-metadata.json` в `dev/release` и `enterprise/release` ссылаются на отсутствующие APK версии 1.2.35, код 10235. Поэтому закрыта локальная проверка подписи и манифеста debug-canary. Для release-приёмки остаются APK/AAB с привязкой к исходникам, требуемыми параметрами release и проверяемым целевым подписантом, а также Android-стенд для испытаний установленного артефакта. Текущее состояние пилота и внешний каталог релизов этой локальной проверкой не измерялись.
