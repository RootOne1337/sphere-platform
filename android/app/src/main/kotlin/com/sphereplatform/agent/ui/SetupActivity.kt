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
import com.sphereplatform.agent.provisioning.ZeroTouchProvisioner
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import timber.log.Timber
import java.util.UUID
import javax.inject.Inject

/**
 * SetupActivity — первоначальная настройка и энролмент агента.
 *
 * Flows:
 * 1. **Already enrolled**: token in AuthTokenStore → start service immediately.
 * 2. **Manual enroll**: Server URL + API Key + optional Device ID form.
 * 3. **QR / deep link**: `sphere://enroll?server=<url>&key=<api_key>&device=<id>`
 *    — parsed from incoming Intent in [onCreate] and [onNewIntent].
 *
 * After enrollment:
 * - Saves server URL, API key (as access_token), device ID to [AuthTokenStore].
 * - Requests battery optimization exemption for 24/7 operation.
 * - Starts [SphereAgentService].
 */
@AndroidEntryPoint
class SetupActivity : AppCompatActivity() {

    @Inject lateinit var authStore: AuthTokenStore
    @Inject lateinit var httpClient: OkHttpClient
    @Inject lateinit var provisioner: ZeroTouchProvisioner

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
        val deviceId = config.deviceId ?: UUID.randomUUID().toString()
        val result = runCatching { verifyCredentials(config.serverUrl, config.apiKey, deviceId) }
        setLoading(false)
        if (result.isSuccess) {
            authStore.saveServerUrl(config.serverUrl)
            authStore.saveApiKey(config.apiKey)
            authStore.saveDeviceId(deviceId)
            showStatus("Auto-enrolled successfully", isError = false)
            requestIgnoreBatteryOptimization()
            launchAgent()
        } else {
            val msg = result.exceptionOrNull()?.message ?: "unknown"
            Timber.w("Zero-touch enrollment failed: $msg")
            showStatus(
                "Auto-provision failed (${config.source}): $msg. Enter credentials manually.",
                isError = true,
            )
            // Fall back to manual form — already inflated
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
            if (it.isNullOrBlank()) UUID.randomUUID().toString() else it
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
            val result = runCatching {
                verifyCredentials(serverUrl, apiKey, deviceId)
            }
            setLoading(false)
            if (result.isSuccess) {
                showStatus(getString(R.string.setup_status_success), isError = false)
                // Persist enrollment data
                authStore.saveServerUrl(serverUrl)
                authStore.saveApiKey(apiKey)
                authStore.saveDeviceId(deviceId)
                requestIgnoreBatteryOptimization()
                launchAgent()
            } else {
                val msg = result.exceptionOrNull()?.message ?: "unknown error"
                Timber.w("Enrollment failed: $msg")
                showStatus(getString(R.string.setup_error_connect, msg), isError = true)
            }
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
