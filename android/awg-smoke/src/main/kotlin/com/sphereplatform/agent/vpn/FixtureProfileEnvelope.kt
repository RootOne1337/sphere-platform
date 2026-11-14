package com.sphereplatform.agent.vpn

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.io.File
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

/** Disposable diagnostic delivery only, not the production credential channel.
 * Public relay stores ciphertext. Recipient private key is generated on-device
 * in AndroidKeyStore and cannot be recovered from the diagnostic APK.
 */
internal object FixtureProfileEnvelope {
    private fun alias(id: UUID) = "sphere-vpn-fixture-$id"
    private fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    fun createRecipient(directory: File, id: UUID) {
        if (store().containsAlias(alias(id))) throw VpnPreparationException("fixture_recipient_exists")
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
        generator.initialize(KeyGenParameterSpec.Builder(alias(id), KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(2048).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_RSA_OAEP)
            .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA1).build())
        val pair = generator.generateKeyPair()
        File(directory, "recipient-public.der").writeBytes(pair.public.encoded)
    }
    fun open(directory: File, id: UUID) {
        val sealed = File(directory, "sealed-profile.json")
        if (sealed.length() !in 1..131072) throw VpnPreparationException("fixture_envelope_bounds")
        try {
            val data = Json.parseToJsonElement(sealed.readText()).jsonObject
            if (data.keys != setOf("operationId", "wrappedKey", "nonce", "ciphertext") || data["operationId"]?.jsonPrimitive?.content != id.toString()) throw IllegalArgumentException()
            fun bytes(name: String) = Base64.decode(data.getValue(name).jsonPrimitive.content, Base64.NO_WRAP)
            val wrapped = bytes("wrappedKey"); val nonce = bytes("nonce"); val cipher = bytes("ciphertext")
            if (wrapped.size != 256 || nonce.size != 12 || cipher.size !in 17..65552) throw IllegalArgumentException()
            val rsa = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding")
            rsa.init(Cipher.DECRYPT_MODE, store().getKey(alias(id), null), OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA1, PSource.PSpecified.DEFAULT))
            val key = rsa.doFinal(wrapped)
            try {
                if (key.size != 32) throw IllegalArgumentException()
                val aes = Cipher.getInstance("AES/GCM/NoPadding")
                aes.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
                aes.updateAAD(id.toString().toByteArray(Charsets.UTF_8))
                val plain = aes.doFinal(cipher)
                try { File(directory, "fixture-client.conf").writeBytes(plain) } finally { plain.fill(0) }
            } finally { key.fill(0) }
        } catch (_: Exception) {
            File(directory, "fixture-client.conf").delete()
            throw VpnPreparationException("fixture_envelope_rejected")
        } finally {
            sealed.delete(); store().deleteEntry(alias(id)); File(directory, "recipient-public.der").delete()
        }
    }
}
