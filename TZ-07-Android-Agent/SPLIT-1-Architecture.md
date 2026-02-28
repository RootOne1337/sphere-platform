# SPLIT-1 — Android Agent Architecture (Hilt DI + Foreground Service)

**ТЗ-родитель:** TZ-07-Android-Agent  
**Ветка:** `stage/7-android`  
**Задача:** `SPHERE-036`  
**Исполнитель:** Android  
**Оценка:** 1 день  
**Блокирует:** TZ-07 SPLIT-2 (WebSocket Client)

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-7` — НЕ в `sphere-platform`.
> Ветка `stage/7-android` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-7
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/7-android
pwd                          # ОБЯЗАНА содержать: sphere-stage-7
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-7 stage/7-android
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/7-android` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/7-android` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `android/app/src/main/kotlin/.../commands/` | `backend/main.py` 🔴 |
| `android/app/src/main/kotlin/.../lua/` | `backend/core/` 🔴 |
| `android/app/src/main/kotlin/.../updates/` | `android/.../encoder/` (TZ-05) 🔴 |
| `android/app/src/main/kotlin/.../service/` | `android/.../vpn/` (TZ-06) 🔴 |
| `tests/android/` | `backend/` (только читать) 🔴 |

---

## Цель Сплита

Базовая архитектура Android агента: Hilt DI, Foreground Service с 24/7 работой, корректная обработка lifecycle, avoidance OOM Killer.

---

## Шаг 1 — Hilt DI Setup

```kotlin
// AndroidAgent/di/AppModule.kt
@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    
    @Provides @Singleton
    fun provideOkHttpClient(authStore: AuthTokenStore): OkHttpClient {
        return OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)   // WS: бесконечный timeout
            .writeTimeout(30, TimeUnit.SECONDS)
            .pingInterval(0, TimeUnit.MILLISECONDS)  // Свой heartbeat поверх WorkManager (см. TZ-03)
            .build()
    }
    
    @Provides @Singleton
    fun provideJsonParser(): Json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
    }
    
    @Provides @Singleton
    fun providePreferences(@ApplicationContext ctx: Context): EncryptedSharedPreferences {
        val masterKey = MasterKey.Builder(ctx)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            ctx, "sphere_prefs", masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        ) as EncryptedSharedPreferences
    }
    
    @Provides @Singleton
    fun provideCoroutineScope(): CoroutineScope =
        CoroutineScope(SupervisorJob() + Dispatchers.Default)
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {
    @Provides @Singleton
    fun provideWebSocketClient(
        httpClient: OkHttpClient,
        authStore: AuthTokenStore,
        json: Json,
    ): SphereWebSocketClient = SphereWebSocketClient(httpClient, authStore, json)
}
```

---

## Шаг 2 — Agent Foreground Service

```kotlin
// AndroidAgent/service/SphereAgentService.kt
@AndroidEntryPoint
class SphereAgentService : Service() {
    
    companion object {
        const val NOTIFICATION_ID = 1
        
        fun start(context: Context) {
            ContextCompat.startForegroundService(
                context, Intent(context, SphereAgentService::class.java)
            )
        }
    }
    
    @Inject lateinit var wsClient: SphereWebSocketClient
    @Inject lateinit var commandHandler: DeviceCommandHandler
    @Inject lateinit var deviceInfo: DeviceInfoProvider
    @Inject lateinit var appScope: CoroutineScope
    
    private val binder = LocalBinder()
    
    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, buildNotification())
        
        // Запустить подключение в корутине
        appScope.launch {
            wsClient.connect(deviceInfo.getDeviceId())
        }
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // STICKY: перезапускать при убийстве системой
        return START_STICKY
    }
    
    private fun buildNotification(): Notification {
        val channel = NotificationChannel(
            "sphere_agent", "Sphere Platform Agent", NotificationManager.IMPORTANCE_MIN
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        
        return NotificationCompat.Builder(this, "sphere_agent")
            .setSmallIcon(R.drawable.ic_sphere)
            .setContentTitle("Sphere Platform")
            .setContentText("Agent running")
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }
    
    override fun onBind(intent: Intent?) = binder
    override fun onDestroy() {
        appScope.launch { wsClient.disconnect() }
        super.onDestroy()
    }
    
    inner class LocalBinder : Binder() {
        fun getService() = this@SphereAgentService
    }
}
```

---

## Шаг 3 — Boot Receiver + Battery Optimization

```kotlin
// AndroidAgent/BootReceiver.kt
@AndroidEntryPoint
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            SphereAgentService.start(context)
        }
    }
}
```

```kotlin
// AndroidAgent/ui/SetupActivity.kt
fun requestIgnoreBatteryOptimization() {
    val pm = getSystemService(PowerManager::class.java)
    if (!pm.isIgnoringBatteryOptimizations(packageName)) {
        startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
            data = Uri.parse("package:$packageName")
        })
    }
}
```

```xml
<!-- AndroidManifest.xml -->
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
<uses-permission android:name="android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

<receiver android:name=".BootReceiver" android:exported="true">
    <intent-filter>
        <action android:name="android.intent.action.BOOT_COMPLETED" />
    </intent-filter>
</receiver>

<service
    android:name=".service.SphereAgentService"
    android:foregroundServiceType="dataSync"
    android:exported="false" />
```

---

## Критерии готовности

- [x] Foreground Service запускается при boot через BroadcastReceiver
- [x] `START_STICKY`: перезапускается после принудительного kill
- [x] Запрос на игнорирование battery optimization при первом запуске
- [x] EncryptedSharedPreferences: ключи никогда не хранятся в plaintext
- [x] Notification: `PRIORITY_MIN` — не мешает пользователю (tray icon)
- [x] HiltAndroidApp в Application class объявлен
- [x] **v4.3.0:** ConfigWatchdog — remote config polling из Git (CONFIG_URL)
- [x] **v4.3.0:** ServiceWatchdog — AlarmManager keepalive каждые 5 мин
- [x] **v4.3.0:** Тройная защита: BootReceiver + START_STICKY + AlarmManager = 100% uptime
- [x] **v4.3.0:** Circuit breaker → ConfigWatchdog.forceCheck() при 10+ failures
- [x] **v4.3.0:** Enrollment gating — сервис НЕ стартует до enrollment
