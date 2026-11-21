package com.sphereplatform.agent.vpn

import androidx.activity.ComponentActivity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.commands.CommandJournal
import dagger.hilt.android.AndroidEntryPoint
import java.io.File
import java.util.UUID
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/** Debug-only own-app bridge for finite real VpnService acceptance. No secrets
 * are accepted in intents, shell args, UI widgets or result files.
 */
@AndroidEntryPoint
class AppVpnCanaryActivity : ComponentActivity() {
    @Inject lateinit var client: AppScopedVpnClient
    @Inject lateinit var commands: CommandJournal
    private val work = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var id: UUID
    private lateinit var directory: File
    private var started = false
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!BuildConfig.APP_SCOPED_VPN_CANARY) { finish(); return }
        try { id = UUID.fromString(intent.getStringExtra("requestId")); require(id.toString() == intent.getStringExtra("requestId")) }
        catch (_: Exception) { finish(); return }
        directory = File(filesDir, "vpn-canary-v1").apply { mkdirs() }
        if (intent.getStringExtra("mode") == "recipient") {
            work.launch {
                try { File(directory, "recipient-$id.der").writeBytes(AppVpnEnvelope.recipient(id)); report("RECIPIENT_READY") }
                catch (_: Exception) { report("FAILED", "vpn_recipient_unavailable") }
                runOnUiThread { finish() }
            }
        } else {
            val consent = if (intent.getBooleanExtra("consent", false)) VpnService.prepare(this) else null
            if (consent != null) {
                if (savedInstanceState == null) startActivityForResult(consent, 1)
            } else execute()
        }
    }
    private fun execute() {
        if (started) return
        started = true
        work.launch {
            var claimed = false
            val input = File(directory, "request-$id.json")
            try {
                when (val claim = commands.claim(id.toString(), executionDomain = "vpn")) {
                    is CommandJournal.Claim.Existing -> { File(directory, "reply-$id.json").writeText(claim.response.toString()); return@launch }
                    CommandJournal.Claim.Started -> claimed = true
                }
                if (input.length() !in 1..132000) throw VpnPreparationException("vpn_canary_input_bounds")
                val body = if (intent.getBooleanExtra("sealed", false)) {
                    val plain = AppVpnEnvelope.open(id, input.readText())
                    try { Json.parseToJsonElement(plain.toString(Charsets.UTF_8)).jsonObject } finally { plain.fill(0) }
                } else Json.parseToJsonElement(input.readText()).jsonObject
                input.delete()
                if (AppVpnCommand.parse(body.toString()).requestId != id) throw VpnPreparationException("vpn_request_identity_invalid")
                val result = client.request(body)
                val failed = result.phase in setOf("CONSENT_REQUIRED", "OPERATION_REJECTED", "OUTCOME_UNKNOWN", "RECONCILIATION_REQUIRED", "STATUS_UNKNOWN")
                val receipt = commands.complete(id.toString(), if (failed) "failed" else "completed", if (failed) result.reason else null,
                    buildJsonObject { put("success", !failed); put("vpn", AppVpnWire.json.encodeToJsonElement(result)) })
                File(directory, "reply-$id.json").writeText(receipt.toString())
            } catch (failure: Exception) {
                val reason = (failure as? VpnPreparationException)?.reason ?: "vpn_canary_operation_unconfirmed"
                if (claimed) runCatching { commands.complete(id.toString(), "failed", reason, null) }
                report("FAILED", reason)
            } finally { input.delete(); runOnUiThread { finish() } }
        }
    }
    private fun report(phase: String, reason: String? = null) {
        File(directory, "reply-$id.json").writeText(buildJsonObject { put("requestId", id.toString()); put("phase", phase); put("reason", reason) }.toString())
    }
    @Deprecated("Android VPN consent result")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode == RESULT_OK) execute() else { report("FAILED", "vpn_consent_declined"); finish() }
    }
    override fun onDestroy() { work.cancel(); super.onDestroy() }
}
