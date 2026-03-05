package com.sphereplatform.agent.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.sphereplatform.agent.R
import com.sphereplatform.agent.commands.AdbActionExecutor
import com.sphereplatform.agent.commands.DeviceCommandHandler
import com.sphereplatform.agent.network.NetworkChangeHandler
import com.sphereplatform.agent.providers.DeviceInfoProvider
import com.sphereplatform.agent.ws.SphereWebSocketClient
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * SphereAgentService — основной Foreground Service агента.
 *
 * Жизненный цикл:
 * - onCreate: регистрирует CommandDispatcher, NetworkChangeHandler, запускает WS
 * - onStartCommand: START_STICKY — перезапуск после kill системой
 * - onDestroy: корректный stop WS + root session
 */
@AndroidEntryPoint
class SphereAgentService : Service() {

    companion object {
        const val NOTIFICATION_ID = 1
        private const val CHANNEL_ID = "sphere_agent"

        fun start(context: Context) {
            ContextCompat.startForegroundService(
                context,
                Intent(context, SphereAgentService::class.java)
            )
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, SphereAgentService::class.java))
        }
    }

    @Inject lateinit var wsClient: SphereWebSocketClient
    @Inject lateinit var commandHandler: DeviceCommandHandler
    @Inject lateinit var networkChangeHandler: NetworkChangeHandler
    @Inject lateinit var adbActions: AdbActionExecutor
    @Inject lateinit var deviceInfo: DeviceInfoProvider
    @Inject lateinit var appScope: CoroutineScope
    @Inject lateinit var configWatchdog: ConfigWatchdog

    /**
     * FIX D1: Service-scoped CoroutineScope — отменяется в onDestroy().
     * appScope (application-level) НЕ отменяется при рестарте сервиса →
     * корутины WS connect, configWatchdog, heartbeat дублируются.
     * serviceScope гарантирует чистую остановку всех фоновых задач.
     */
    private val serviceScope = CoroutineScope(kotlinx.coroutines.SupervisorJob() + Dispatchers.Default)

    private val binder = LocalBinder()

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, buildNotification())

        // 1. Регистрируем callbacks ПЕРЕД подключением (иначе пропустим onConnected)
        commandHandler.start()

        // 2. Мониторинг сети
        networkChangeHandler.register()

        // 3. Circuit breaker hook — при открытии CB проверяем конфиг из Git
        wsClient.onCircuitBreakerOpen = {
            serviceScope.launch(Dispatchers.IO) { configWatchdog.forceCheck() }
        }

        // 4. Запускаем WS-подключение (reconnect loop)
        serviceScope.launch {
            wsClient.connect(deviceInfo.getDeviceId())
        }

        // 5. ConfigWatchdog — периодический опрос конфига из GitHub (CONFIG_URL)
        //    Если server_url сменился → обновляет store и форсирует reconnect
        serviceScope.launch(Dispatchers.IO) {
            configWatchdog.run()
        }

        // 6. ServiceWatchdog — AlarmManager гарантирует перезапуск после OOM kill
        ServiceWatchdog.schedule(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // START_STICKY: Android перезапустит сервис с null intent если будет убит системой
        return START_STICKY
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL_ID) == null) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Sphere Platform Agent",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Работа агента в фоне"
                setShowBadge(false)
            }
            manager.createNotificationChannel(channel)
        }

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_sphere)
            .setContentTitle("Sphere Platform")
            .setContentText("Agent running")
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setSilent(true)
            .build()
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onDestroy() {
        // FIX D1: Отменяем все service-scoped корутины (WS, configWatchdog, heartbeat)
        serviceScope.cancel()
        // FIX D1: Отменяем heartbeat watchdog loop в CommandDispatcher
        commandHandler.dispatcher.stop()
        configWatchdog.stop()
        // FIX AUDIT-2.7: Корректная отписка NetworkCallback
        networkChangeHandler.unregister()
        wsClient.disconnect()
        adbActions.closeRootSession()
        super.onDestroy()
    }

    inner class LocalBinder : Binder() {
        fun getService(): SphereAgentService = this@SphereAgentService
    }
}
