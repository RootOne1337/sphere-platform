package com.sphereplatform.agent.ui

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.lifecycleScope
import com.google.android.material.card.MaterialCardView
import com.google.android.material.chip.Chip
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.R
import com.sphereplatform.agent.provisioning.DeviceRegistrationClient
import com.sphereplatform.agent.provisioning.RegistrationException
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber
import java.util.UUID
import javax.inject.Inject

/**
 * SetupActivity — первоначальная настройка и энролмент агента.
 *
 * Flows:
 * 1. **Already enrolled**: токен в AuthTokenStore → сразу запуск сервиса.
 * 2. **Auto-register**: ZeroTouchProvisioner обнаружил конфиг с autoRegister=true
 *    → DeviceRegistrationClient автоматически регистрирует устройство.
 * 3. **Manual enroll**: Server URL + API Key + optional Device ID форма.
 * 4. **QR / deep link**: `sphere://enroll?server=<url>&key=<api_key>&device=<id>`
 *    — парсится из Intent в [onCreate] и [onNewIntent].
 *
 * После энролмента:
 * - Сохраняет server URL, device_id, JWT (access + refresh) в [AuthTokenStore].
 * - Запрашивает exemption от battery optimization для 24/7 работы.
 * - Запускает [SphereAgentService].
 */
@AndroidEntryPoint
class SetupActivity : AppCompatActivity() {

    @Inject lateinit var authStore: AuthTokenStore
    @Inject lateinit var httpClient: OkHttpClient
    @Inject lateinit var provisioner: ZeroTouchProvisioner
    @Inject lateinit var registrationClient: DeviceRegistrationClient

    private lateinit var tilServerUrl: TextInputLayout
    private lateinit var tilApiKey: TextInputLayout
    private lateinit var tilDeviceId: TextInputLayout
    private lateinit var etServerUrl: TextInputEditText
    private lateinit var etApiKey: TextInputEditText
    private lateinit var etDeviceId: TextInputEditText
    private lateinit var btnEnroll: Button
    private lateinit var tvStatus: TextView
    private lateinit var progressBar: LinearProgressIndicator
    private lateinit var cardStatus: MaterialCardView
    private lateinit var chipVersion: Chip
    private lateinit var tvDeviceInfo: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)

        // Already enrolled → launch service immediately
        if (authStore.getToken() != null) {
            launchAgent()
            return
        }

        setContentView(R.layout.activity_setup)
        bindViews()

        // Zero-touch: discover config automatically before showing manual form
        val autoConfig = provisioner.discoverConfig()
        if (autoConfig != null) {
            showStatus("Auto-provision via ${autoConfig.source}…", isError = false)
            setLoading(true)
            lifecycleScope.launch { performAutoEnroll(autoConfig) }
            return
        }

        // Check for deep-link / QR enrollment data in the launching Intent
        handleEnrollIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleEnrollIntent(intent)
    }

    // ── Binding ────────────────────────────────────────────────────────────

    private fun bindViews() {
        tilServerUrl = findViewById(R.id.tilServerUrl)
        tilApiKey    = findViewById(R.id.tilApiKey)
        tilDeviceId  = findViewById(R.id.tilDeviceId)
        etServerUrl  = findViewById(R.id.etServerUrl)
        etApiKey     = findViewById(R.id.etApiKey)
        etDeviceId   = findViewById(R.id.etDeviceId)
        btnEnroll    = findViewById(R.id.btnEnroll)
        tvStatus     = findViewById(R.id.tvStatus)
        progressBar  = findViewById(R.id.progressBar)
        cardStatus   = findViewById(R.id.cardStatus)
        chipVersion  = findViewById(R.id.chipVersion)
        tvDeviceInfo = findViewById(R.id.tvDeviceInfo)

        chipVersion.text = "v${BuildConfig.VERSION_NAME}"
        tvDeviceInfo.text = "${Build.MANUFACTURER} ${Build.MODEL} \u00b7 Android ${Build.VERSION.RELEASE}"

        btnEnroll.setOnClickListener { onEnrollClicked() }
    }

    // ── Zero-touch auto-enrollment ─────────────────────────────────────────

    private suspend fun performAutoEnroll(config: ZeroTouchProvisioner.ProvisionConfig) {
        // Если autoRegister включён и API-ключ пуст (config_endpoint) → авто-регистрация
        if (config.autoRegisterEnabled && config.apiKey.isBlank()) {
            performAutoRegistration(config.serverUrl)
            return
        }

        // Классический flow: API-ключ есть → verify + save
        if (config.apiKey.isNotBlank()) {
            performAutoEnrollWithApiKey(config)
            return
        }

        // Есть server_url но нет API-ключа и нет autoRegister → ручной ввод
        setLoading(false)
        showStatus("Server found (${config.source}), enter API key manually.", isError = false)
    }

    /**
     * Авто-регистрация через POST /api/v1/devices/register.
     * Не требует API-ключ от пользователя — используется enrollment key из конфига.
     */
    private suspend fun performAutoRegistration(serverUrl: String) {
        showStatus("Auto-registering device…", isError = false)

        // Получаем enrollment API key из конфига (config endpoint или файл)
        val enrollmentKey = getEnrollmentKeyFromConfig(serverUrl)
        if (enrollmentKey == null) {
            setLoading(false)
            showStatus("Auto-register: enrollment key not found. Enter credentials manually.", isError = true)
            return
        }

        val result = runCatching {
            registrationClient.register(
                serverUrl = serverUrl,
                enrollmentApiKey = enrollmentKey,
            )
        }

        setLoading(false)
        if (result.isSuccess) {
            val reg = result.getOrThrow()
            showStatus(
                "Registered: ${reg.name} (${if (reg.isNew) "new" else "re-enrolled"})",
                isError = false,
            )
            requestIgnoreBatteryOptimization()
            launchAgent()
        } else {
            val ex = result.exceptionOrNull()
            val msg = if (ex is RegistrationException) {
                "HTTP ${ex.httpCode}: ${ex.message}"
            } else {
                ex?.message ?: "unknown"
            }
            Timber.w("Auto-registration failed: $msg")
            showStatus("Auto-register failed: $msg. Enter credentials manually.", isError = true)
        }
    }

    /**
     * Получает enrollment API key из server config endpoint или локальных источников.
     * Prioritет: config endpoint → локальный файл → BuildConfig.DEFAULT_API_KEY.
     */
    private fun getEnrollmentKeyFromConfig(serverUrl: String): String? {
        // Пробуем получить ключ из config endpoint (server возвращает enrollment_api_key)
        val serverConfig = provisioner.fetchServerConfig()
        if (serverConfig?.enrollmentApiKey != null) {
            return serverConfig.enrollmentApiKey
        }
        // Пробуем из локального конфиг-файла (adb push)
        val localConfig = provisioner.discoverConfig()
        if (localConfig != null && localConfig.apiKey.isNotBlank()) {
            return localConfig.apiKey
        }
        // BuildConfig fallback
        return BuildConfig.DEFAULT_API_KEY.takeIf { it.isNotBlank() }
    }

    /**
     * Классический auto-enroll: API-ключ уже есть (из конфиг-файла/MDM).
     * Сначала пробуем авто-регистрацию через DeviceRegistrationClient,
     * если не получится — fallback на простую проверку credentials.
     */
    private suspend fun performAutoEnrollWithApiKey(config: ZeroTouchProvisioner.ProvisionConfig) {
        // Сначала пробуем авто-регистрацию (серверу нужен enrollment key)
        val regResult = runCatching {
            registrationClient.register(
                serverUrl = config.serverUrl,
                enrollmentApiKey = config.apiKey,
            )
        }

        setLoading(false)
        if (regResult.isSuccess) {
            val reg = regResult.getOrThrow()
            showStatus(
                "Auto-enrolled: ${reg.name} (${if (reg.isNew) "new" else "existing"})",
                isError = false,
            )
            requestIgnoreBatteryOptimization()
            launchAgent()
            return
        }

        // Fallback: ключ может быть не enrollment (нет device:register) → старый flow
        val ex = regResult.exceptionOrNull()
        if (ex is RegistrationException && ex.httpCode == 403) {
            Timber.d("Auto-register: API key lacks device:register, falling back to legacy enroll")
            performLegacyAutoEnroll(config)
            return
        }

        val msg = ex?.message ?: "unknown"
        Timber.w("Auto-enrollment failed: $msg")
        showStatus("Auto-provision failed (${config.source}): $msg. Enter credentials manually.", isError = true)
    }

    /**
     * Legacy auto-enroll: сохраняем API-ключ как токен (без JWT).
     * Совместимость с текущими deployment'ами, где enrollment отсутствует.
     */
    private suspend fun performLegacyAutoEnroll(config: ZeroTouchProvisioner.ProvisionConfig) {
        val deviceId = config.deviceId ?: UUID.randomUUID().toString()
        val result = runCatching { verifyCredentials(config.serverUrl, config.apiKey, deviceId) }
        setLoading(false)
        if (result.isSuccess) {
            authStore.saveServerUrl(config.serverUrl)
            authStore.saveApiKey(config.apiKey)
            authStore.saveDeviceId(deviceId)
            showStatus("Auto-enrolled successfully (legacy)", isError = false)
            requestIgnoreBatteryOptimization()
            launchAgent()
        } else {
            val msg = result.exceptionOrNull()?.message ?: "unknown"
            Timber.w("Legacy auto-enrollment failed: $msg")
            showStatus("Auto-provision failed (${config.source}): $msg.", isError = true)
        }
    }

    // ── Deep-link (sphere://enroll?server=…&key=…&device=…) ───────────────

    private fun handleEnrollIntent(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme != "sphere" || data.host != "enroll") return

        val server = data.getQueryParameter("server")?.takeIf { it.isNotBlank() } ?: return
        val key    = data.getQueryParameter("key")?.takeIf { it.isNotBlank() } ?: return
        val device = data.getQueryParameter("device")

        Timber.i("SetupActivity: deep-link enroll, server=$server")

        if (::etServerUrl.isInitialized) {
            etServerUrl.setText(server)
            etApiKey.setText(key)
            etDeviceId.setText(device ?: "")
        } else {
            // Views not yet inflated — start enrollment directly
            setContentView(R.layout.activity_setup)
            bindViews()
            etServerUrl.setText(server)
            etApiKey.setText(key)
            etDeviceId.setText(device ?: "")
        }
        onEnrollClicked()
    }

    // ── Manual enrollment ─────────────────────────────────────────────────

    private fun onEnrollClicked() {
        val serverUrl = etServerUrl.text?.toString()?.trim() ?: ""
        val apiKey    = etApiKey.text?.toString()?.trim() ?: ""
        val deviceId  = etDeviceId.text?.toString()?.trim().let {
            if (it.isNullOrBlank()) null else it
        }

        // Validation
        tilServerUrl.error = null
        tilApiKey.error = null

        if (serverUrl.isEmpty() || apiKey.isEmpty()) {
            if (serverUrl.isEmpty()) tilServerUrl.error = getString(R.string.setup_error_empty_fields)
            if (apiKey.isEmpty())    tilApiKey.error    = getString(R.string.setup_error_empty_fields)
            return
        }
        if (!BuildConfig.ALLOW_HTTP && !serverUrl.startsWith("https://")) {
            tilServerUrl.error = getString(R.string.setup_error_invalid_url)
            return
        }

        hideKeyboard()
        setLoading(true)
        showStatus(getString(R.string.setup_status_connecting), isError = false)

        lifecycleScope.launch {
            // Пробуем авто-регистрацию через DeviceRegistrationClient
            val regResult = runCatching {
                registrationClient.register(
                    serverUrl = serverUrl,
                    enrollmentApiKey = apiKey,
                )
            }

            if (regResult.isSuccess) {
                setLoading(false)
                val reg = regResult.getOrThrow()
                showStatus(
                    getString(R.string.setup_status_success) + " (${reg.name})",
                    isError = false,
                )
                requestIgnoreBatteryOptimization()
                launchAgent()
                return@launch
            }

            // Fallback: если 403 (нет device:register) → legacy enroll
            val ex = regResult.exceptionOrNull()
            if (ex is RegistrationException && ex.httpCode == 403) {
                Timber.d("Manual enroll: API key lacks device:register, using legacy flow")
                val legacyDeviceId = deviceId ?: UUID.randomUUID().toString()
                val legacyResult = runCatching {
                    verifyCredentials(serverUrl, apiKey, legacyDeviceId)
                }
                setLoading(false)
                if (legacyResult.isSuccess) {
                    showStatus(getString(R.string.setup_status_success), isError = false)
                    authStore.saveServerUrl(serverUrl)
                    authStore.saveApiKey(apiKey)
                    authStore.saveDeviceId(legacyDeviceId)
                    requestIgnoreBatteryOptimization()
                    launchAgent()
                } else {
                    val msg = legacyResult.exceptionOrNull()?.message ?: "unknown error"
                    Timber.w("Legacy enrollment failed: $msg")
                    showStatus(getString(R.string.setup_error_connect, msg), isError = true)
                }
                return@launch
            }

            setLoading(false)
            val msg = ex?.message ?: "unknown error"
            Timber.w("Enrollment failed: $msg")
            showStatus(getString(R.string.setup_error_connect, msg), isError = true)
        }
    }

    /**
     * Verifies credentials by calling [GET /api/v1/devices/me] with the API key.
     * A successful HTTP 200 confirms the key is valid and the server is reachable.
     */
    private suspend fun verifyCredentials(server: String, apiKey: String, deviceId: String) {
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("$server/api/v1/devices/me")
                .header("X-API-Key", apiKey)
                .header("X-Device-Id", deviceId)
                .build()
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful && response.code != 404) {
                    // 404 is acceptable — device may not be pre-registered
                    throw IllegalStateException("HTTP ${response.code}: ${response.message}")
                }
            }
        }
    }

    // ── Post-enrollment ───────────────────────────────────────────────────

    private fun requestIgnoreBatteryOptimization() {
        val pm = getSystemService(PowerManager::class.java)
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            runCatching {
                startActivity(
                    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                        data = Uri.parse("package:$packageName")
                    }
                )
            }
        }
    }

    private fun launchAgent() {
        SphereAgentService.start(this)
        finish()
    }

    // ── UI helpers ────────────────────────────────────────────────────────

    private fun setLoading(loading: Boolean) {
        btnEnroll.isEnabled = !loading
        progressBar.visibility = if (loading) View.VISIBLE else View.GONE
    }

    private fun showStatus(msg: String, isError: Boolean) {
        cardStatus.visibility = View.VISIBLE
        tvStatus.text = msg
        tvStatus.setTextColor(
            if (isError) getColor(R.color.brand_error) else getColor(R.color.brand_primary_light)
        )
    }

    private fun hideKeyboard() {
        currentFocus?.let { view ->
            val imm = getSystemService(InputMethodManager::class.java)
            imm.hideSoftInputFromWindow(view.windowToken, 0)
        }
    }
}
