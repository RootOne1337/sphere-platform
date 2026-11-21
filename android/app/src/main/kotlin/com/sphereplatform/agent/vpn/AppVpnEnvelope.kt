package com.sphereplatform.agent.vpn

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.spec.MGF1ParameterSpec
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.OAEPParameterSpec
import javax.crypto.spec.PSource
import javax.crypto.spec.SecretKeySpec
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** One-use recipient per operation. Private keys stay inside AndroidKeyStore;
 * secret-bearing plaintext is returned only in memory to the own-UID client.
 */
internal object AppVpnEnvelope {
    private const val PREFIX = "sphere_app_vpn_operation_v1_"
    private fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    @Synchronized fun expiresAt(operation: UUID): Long =
        (store().getCreationDate(PREFIX + operation)?.time ?: throw VpnPreparationException("vpn_recipient_unavailable")) + 300000
    @Synchronized fun recipient(operation: UUID): ByteArray {
        try {
            val keys = store(); val alias = PREFIX + operation
            val now = System.currentTimeMillis()
            if (keys.containsAlias(alias)) {
                val created = keys.getCreationDate(alias)?.time ?: throw VpnPreparationException("vpn_recipient_expired")
                if (now - created !in 0..300000) throw VpnPreparationException("vpn_recipient_expired")
                return keys.getCertificate(alias).publicKey.encoded
            }
            val aliases = java.util.Collections.list(keys.aliases()).filter { it.startsWith(PREFIX) }
            aliases.forEach { old -> keys.getCreationDate(old)?.let { if (now - it.time > 300000) keys.deleteEntry(old) } }
            if (java.util.Collections.list(keys.aliases()).count { it.startsWith(PREFIX) } >= 32) throw VpnPreparationException("vpn_recipient_capacity_exhausted")
            val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
            generator.initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(2048).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_RSA_OAEP)
                .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA1).build())
            return generator.generateKeyPair().public.encoded
        } catch (failure: VpnPreparationException) { throw failure }
          catch (_: Exception) { throw VpnPreparationException("vpn_recipient_unavailable") }
    }
    @Synchronized fun open(operation: UUID, envelope: String): ByteArray {
        if (envelope.toByteArray(Charsets.UTF_8).size !in 1..132000) throw VpnPreparationException("vpn_envelope_bounds")
        val keys = store(); val alias = PREFIX + operation
        try {
            val data = Json.parseToJsonElement(envelope).jsonObject
            if (data.keys != setOf("operationId", "wrappedKey", "nonce", "ciphertext") || data["operationId"]?.jsonPrimitive?.content != operation.toString()) throw IllegalArgumentException()
            val created = keys.getCreationDate(alias) ?: throw IllegalArgumentException()
            if (System.currentTimeMillis() - created.time !in 0..300000) throw IllegalArgumentException()
            fun bytes(name: String) = Base64.decode(data.getValue(name).jsonPrimitive.content, Base64.NO_WRAP)
            val wrapped = bytes("wrappedKey"); val nonce = bytes("nonce"); val cipher = bytes("ciphertext")
            if (wrapped.size != 256 || nonce.size != 12 || cipher.size !in 17..98320) throw IllegalArgumentException()
            val rsa = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding")
            rsa.init(Cipher.DECRYPT_MODE, keys.getKey(alias, null), OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA1, PSource.PSpecified.DEFAULT))
            val key = rsa.doFinal(wrapped)
            try {
                if (key.size != 32) throw IllegalArgumentException()
                val aes = Cipher.getInstance("AES/GCM/NoPadding")
                aes.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
                aes.updateAAD(operation.toString().toByteArray(Charsets.UTF_8))
                return aes.doFinal(cipher)
            } finally { key.fill(0) }
        } catch (_: Exception) { throw VpnPreparationException("vpn_envelope_rejected") }
        finally { runCatching { keys.deleteEntry(alias) } }
    }
}
