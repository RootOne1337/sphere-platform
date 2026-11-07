package com.sphereplatform.agent.vpn

import android.content.Context
import android.content.Intent
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import androidx.core.content.ContextCompat
import com.sphereplatform.agent.BuildConfig
import java.io.File
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive

internal fun currentVpnBootId(): String = try {
    File("/proc/sys/kernel/random/boot_id").readText().trim().also { require(UUID.fromString(it).toString() == it) }
} catch (_: Exception) { throw VpnPreparationException("vpn_boot_identity_unavailable") }

internal interface VpnRestartCipher {
    fun seal(clear: ByteArray): ByteArray
    fun open(sealed: ByteArray): ByteArray
}

internal class AndroidVpnRestartCipher(private val packageName: String) : VpnRestartCipher {
    private val alias = "sphere_app_vpn_restart_v1"
    private val aad get() = (packageName + ":vpn-restart-v1").toByteArray(Charsets.UTF_8)
    @Synchronized private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(alias)) return store.getKey(alias, null) as SecretKey
        if (!create) throw VpnPreparationException("vpn_restart_key_unavailable")
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).setUserAuthenticationRequired(false).build())
        }.generateKey()
    }
    override fun seal(clear: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(true)); cipher.updateAAD(aad)
        require(cipher.iv.size == 12)
        return byteArrayOf(1) + cipher.iv + cipher.doFinal(clear)
    }
    override fun open(sealed: ByteArray): ByteArray {
        require(sealed.size in 30..131072 && sealed[0] == 1.toByte())
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, sealed.copyOfRange(1, 13)))
        cipher.updateAAD(aad)
        return cipher.doFinal(sealed, 13, sealed.size - 13)
    }
}

internal class VpnRestartState(val command: AppVpnCommand, val bootId: String, val paused: Boolean) {
    override fun toString() = "VpnRestartState([redacted])"
}

/** CE storage, atomic encrypted payload, no plaintext profile/key cache. A
 * non-secret stop tombstone wins even if a process dies during teardown. */
internal class AppVpnRestartStore(private val directory: File, private val cipher: VpnRestartCipher) {
    private val payload = AtomicFile(File(directory, "restart.enc"))
    private val stopped get() = File(directory, "restart.disabled")
    @Synchronized fun save(command: AppVpnCommand, bootId: String, paused: Boolean, enableAfterStop: Boolean = false) {
        if (!enableAfterStop && (stopped.exists() || File(stopped.path + ".bak").exists())) throw VpnPreparationException("vpn_restart_disabled")
        require(UUID.fromString(bootId).toString() == bootId)
        val clear = JsonObject(mapOf("schema" to JsonPrimitive(1), "boot_id" to JsonPrimitive(bootId),
            "desired" to JsonPrimitive(if (paused) "paused" else "active"), "command" to command.restartPayload())).toString().toByteArray(Charsets.UTF_8)
        try {
            require(clear.size <= 110000)
            val encrypted = cipher.seal(clear)
            require(encrypted.size in 30..131072)
            directory.mkdirs()
            val stream = payload.startWrite()
            try { stream.write(encrypted); payload.finishWrite(stream) }
            catch (failure: Exception) { payload.failWrite(stream); throw failure }
            // Removing this marker is permitted only after a complete new save.
            if (enableAfterStop) {
                AtomicFile(stopped).delete()
                if (stopped.exists() || File(stopped.path + ".bak").exists()) throw VpnPreparationException("vpn_restart_disabled")
            }
        } finally { clear.fill(0) }
    }
    @Synchronized fun disable() {
        directory.mkdirs()
        val file = AtomicFile(stopped); val stream = file.startWrite()
        try { stream.write(byteArrayOf(1)); file.finishWrite(stream) }
        catch (failure: Exception) { file.failWrite(stream); throw failure }
    }
    @Synchronized fun read(): VpnRestartState? {
        if (stopped.exists() || File(stopped.path + ".bak").exists()) return null
        if (!payload.baseFile.exists() && !File(payload.baseFile.path + ".bak").exists()) return null
        try {
            val sealed = payload.openRead().use { it.readBytesLimited(131072) }
            val clear = cipher.open(sealed)
            try {
                require(clear.size in 1..110000)
                val value = Json.parseToJsonElement(clear.toString(Charsets.UTF_8)) as JsonObject
                require(value.keys == setOf("schema", "boot_id", "desired", "command"))
                require(value.getValue("schema") == JsonPrimitive(1))
                val boot = value.getValue("boot_id").jsonPrimitive.content
                require(UUID.fromString(boot).toString() == boot)
                val desired = value.getValue("desired").jsonPrimitive.content
                require(desired in setOf("active", "paused"))
                return VpnRestartState(AppVpnCommand.parse(value.getValue("command").toString()), boot, desired == "paused")
            } finally { clear.fill(0) }
        } catch (_: Exception) { throw VpnPreparationException("vpn_restart_state_unavailable") }
    }
    private fun java.io.InputStream.readBytesLimited(limit: Int): ByteArray {
        val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(4096)
        while (true) {
            val n = read(buffer); if (n < 0) return output.toByteArray()
            require(output.size() + n <= limit); output.write(buffer, 0, n)
        }
    }
}

/** Starts only a previously provisioned native service; never enrolls or opens
 * control/media inside the VPN process. CE unlock is required. */
internal object AppVpnAutoStart {
    const val RESTORE = "com.sphereplatform.agent.vpn.RESTORE_AFTER_BOOT"
    fun hasState(context: Context): Boolean {
        return try {
            if (!BuildConfig.APP_SCOPED_VPN_CANARY || VpnProcessIdentity.isVpnProcess(context)) return false
            val directory = File(context.filesDir, "app-vpn-v1")
            if (File(directory, "restart.disabled").exists() || File(directory, "restart.disabled.bak").exists()) return false
            File(directory, "restart.enc").exists() || File(directory, "restart.enc.bak").exists()
        } catch (_: Exception) { false } // VPN storage must never prevent management startup.
    }
    fun start(context: Context) {
        if (!hasState(context)) return
        try { ContextCompat.startForegroundService(context, Intent(context, AppScopedVpnService::class.java).setAction(RESTORE)) }
        catch (_: Exception) { /* Android/OEM may postpone FGS startup; existing boot/job paths can try later. */ }
    }
}
