package com.sphereplatform.agent.ui

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.appcompat.app.AppCompatActivity
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * SetupActivity — первоначальная настройка агента.
 *
 * Отображается при первом запуске. Отвечает за:
 * 1. Запрос на игнорирование battery optimization (24/7 работа)
 * 2. Запуск SphereAgentService после завершения настройки
 */
@AndroidEntryPoint
class SetupActivity : AppCompatActivity() {

    @Inject
    lateinit var authStore: AuthTokenStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Если токен уже есть — сразу запускаем сервис
        if (authStore.getToken() != null) {
            SphereAgentService.start(this)
            finish()
            return
        }

        requestIgnoreBatteryOptimization()
    }

    /**
     * Запрашивает исключение из battery optimization для 24/7 работы.
     * Без этого Android может убивать сервис при агрессивной оптимизации.
     */
    fun requestIgnoreBatteryOptimization() {
        val pm = getSystemService(PowerManager::class.java)
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$packageName")
                }
            )
        }
    }
}
