# SPLIT-1 — MediaProjection Setup (Android Screen Capture)

**ТЗ-родитель:** TZ-05-H264-Streaming  
**Ветка:** `stage/5-streaming`  
**Задача:** `SPHERE-026`  
**Исполнитель:** Android  
**Оценка:** 1 день  
**Блокирует:** TZ-05 SPLIT-2 (MediaCodec)

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-5` — НЕ в `sphere-platform`.
> Ветка `stage/5-streaming` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-5
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/5-streaming
pwd                          # ОБЯЗАНА содержать: sphere-stage-5
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-5 stage/5-streaming
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/5-streaming` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/5-streaming` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `android/app/src/main/kotlin/.../encoder/` | `backend/main.py` 🔴 |
| `android/app/src/main/kotlin/.../service/ScreenCaptureService*` | `backend/core/` 🔴 |
| `backend/api/v1/streaming/` | `backend/websocket/` (TZ-03) 🔴 |
| `backend/services/streaming_*` | `android/.../vpn/` (TZ-06) 🔴 |
| `tests/test_streaming*` | `docker-compose*.yml` 🔴 |

---

## Цель Сплита

Захват экрана через MediaProjection API. Foreground Service с постоянным уведомлением. Корректная обработка lifecycle (pause/resume, configuration changes).

---

## Предусловия

- Android API 21+ (MediaProjection)
- Разрешение: `FOREGROUND_SERVICE_MEDIA_PROJECTION` (API 34+)
- KernelSU root: не требуется (MediaProjection работает без root)

---

## Шаг 1 — MediaProjection Service

```kotlin
// AndroidAgent/streaming/ScreenCaptureService.kt
@AndroidEntryPoint
class ScreenCaptureService : Service() {
    
    companion object {
        const val ACTION_START = "action.START_CAPTURE"
        const val ACTION_STOP = "action.STOP_CAPTURE"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val NOTIFICATION_ID = 1001
    }
    
    @Inject lateinit var streamingManager: StreamingManager
    
    private var mediaProjection: MediaProjection? = null
    private val mediaProjectionManager by lazy {
        getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    }
    
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                startForeground(NOTIFICATION_ID, buildNotification())
                val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
                val resultData = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
                    ?: run { stopSelf(); return START_NOT_STICKY }
                
                mediaProjection = mediaProjectionManager.getMediaProjection(resultCode, resultData)
                mediaProjection?.registerCallback(projectionCallback, null)
                streamingManager.start(mediaProjection!!)
            }
            ACTION_STOP -> {
                streamingManager.stop()
                mediaProjection?.stop()
                mediaProjection = null
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }
    
    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            // Система остановила projection (например, пользователь нажал кнопку)
            streamingManager.stop()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }
    
    private fun buildNotification(): Notification {
        val channelId = "screen_capture"
        val channel = NotificationChannel(
            channelId, "Screen Capture", NotificationManager.IMPORTANCE_LOW
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        
        return NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_screen_share)
            .setContentTitle("Sphere Platform")
            .setContentText("Screen sharing active")
            .setOngoing(true)
            .build()
    }
    
    override fun onBind(intent: Intent?) = null
}
```

---

## Шаг 2 — VirtualDisplay Creator

```kotlin
// AndroidAgent/streaming/VirtualDisplayManager.kt
class VirtualDisplayManager(
    private val context: Context,
    private val mediaProjection: MediaProjection,
) {
    data class DisplayConfig(
        val width: Int = 1280,
        val height: Int = 720,
        val dpi: Int = 320,
    )
    
    private var virtualDisplay: VirtualDisplay? = null
    private var surface: Surface? = null
    
    // LOW-5: параметр переименован: encoderSurface (ясно что требуется Surface, не MediaCodec)
    fun createDisplay(config: DisplayConfig, encoderSurface: Surface): VirtualDisplay {
        surface = encoderSurface
        
        virtualDisplay = mediaProjection.createVirtualDisplay(
            "SphereCapture",
            config.width,
            config.height,
            config.dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            surface,
            null,  // callback
            null,  // handler
        )
        return virtualDisplay!!
    }
    
    fun release() {
        virtualDisplay?.release()
        virtualDisplay = null
        surface?.release()
        surface = null
    }
}
```

---

## Шаг 3 — ScreenCapture Activity (Permission Request)

```kotlin
// AndroidAgent/streaming/ScreenCaptureRequestActivity.kt
class ScreenCaptureRequestActivity : AppCompatActivity() {
    
    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            // Запустить сервис с разрешением
            startForegroundService(Intent(this, ScreenCaptureService::class.java).apply {
                action = ScreenCaptureService.ACTION_START
                putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, result.data)
            })
        } else {
            // Разрешение denied — отправить ответ серверу
            sendBroadcast(Intent("sphere.SCREEN_CAPTURE_DENIED"))
        }
        finish()
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Прозрачная Activity — сразу запросить разрешение
        val mpManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(mpManager.createScreenCaptureIntent())
    }
}
```

---

## Шаг 4 — AndroidManifest

```xml
<!-- AndroidManifest.xml (дополнения) -->
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />

<service
    android:name=".streaming.ScreenCaptureService"
    android:foregroundServiceType="mediaProjection"
    android:exported="false" />

<activity
    android:name=".streaming.ScreenCaptureRequestActivity"
    android:theme="@android:style/Theme.Translucent.NoTitleBar"
    android:exported="false" />
```

---

## Критерии готовности

- [ ] Foreground Service запускается с `foregroundServiceType="mediaProjection"`
- [ ] VirtualDisplay создаётся с Surface от MediaCodec
- [ ] `MediaProjection.Callback.onStop()` корректно останавливает сервис
- [ ] API 34+: разрешение `FOREGROUND_SERVICE_MEDIA_PROJECTION` объявлено
- [ ] Прозрачная Activity запрашивает разрешение без UI
- [ ] Повторный старт при уже активном стриминге: корректный restart
