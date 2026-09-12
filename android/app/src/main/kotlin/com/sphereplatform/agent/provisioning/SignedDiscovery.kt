package com.sphereplatform.agent.provisioning

import android.util.AtomicFile
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONObject
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.interfaces.RSAPublicKey
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import java.util.UUID

/** Fixed signature algorithm; only explicitly provisioned public keys establish trust. */
internal class SignedManifestVerifier(
    private val installationId: String,
    encodedKeys: Map<String, String>,
) {
    private val keys = encodedKeys.mapValues { (_, encoded) ->
        val key = KeyFactory.getInstance("RSA").generatePublic(
            X509EncodedKeySpec(Base64.getDecoder().decode(encoded))) as RSAPublicKey
        require(key.modulus.bitLength() in 2048..4096) { "Invalid discovery key size" }
        key
    }

    init {
        require(UUID.fromString(installationId).toString() == installationId)
        require(keys.isNotEmpty() && keys.size <= 4)
    }

    fun verify(envelope: JSONObject): VerifiedManifest {
        require(envelope.keys().asSequence().toSet() == setOf("key_id", "payload", "signature"))
        val key = keys[envelope.getString("key_id")] ?: error("Unknown discovery key")
        val payloadBytes = Base64.getDecoder().decode(envelope.getString("payload"))
        require(payloadBytes.size <= 32 * 1024)
        val signature = Base64.getDecoder().decode(envelope.getString("signature"))
        val verifier = Signature.getInstance("SHA256withRSA")
        verifier.initVerify(key)
        verifier.update(payloadBytes)
        require(verifier.verify(signature)) { "Invalid discovery signature" }
        val payload = JSONObject(String(payloadBytes, Charsets.UTF_8))
        val required = setOf("schema_version", "installation_id", "config_version", "issued_at",
            "expires_at", "server_url")
        val names = payload.keys().asSequence().toSet()
        require(names.containsAll(required) && (names - required - "fallback_server_url").isEmpty())
        require(payload.strictLong("schema_version") == 1L)
        require(payload.getString("installation_id") == installationId) { "Different discovery installation" }
        val version = payload.strictLong("config_version")
        require(version in 1..9_007_199_254_740_991L)
        val issued = payload.strictLong("issued_at")
        val expires = payload.strictLong("expires_at")
        require(issued in 1..253_402_300_799L && expires in (issued + 1)..253_402_300_799L)
        val primary = httpsEndpoint(payload.getString("server_url"))
        val fallback = if (payload.isNull("fallback_server_url")) null else
            httpsEndpoint(payload.getString("fallback_server_url")).takeIf { it != primary }
        val digest = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(payloadBytes))
        return VerifiedManifest(envelope.toString(), version, issued, expires, primary, fallback, digest)
    }

    private fun JSONObject.strictLong(name: String): Long {
        val value = get(name)
        require(value is Int || value is Long) { "Invalid discovery integer" }
        return (value as Number).toLong()
    }

    companion object {
        fun httpsEndpoint(value: String): String {
            val url = value.toHttpUrlOrNull() ?: error("Invalid discovery URL")
            require(url.isHttps && url.username.isEmpty() && url.password.isEmpty() &&
                url.query == null && url.fragment == null && url.encodedPath == "/")
            return url.toString().trimEnd('/')
        }
    }
}

internal data class VerifiedManifest(
    val envelope: String,
    val version: Long,
    val issuedAt: Long,
    val expiresAt: Long,
    val serverUrl: String,
    val fallbackServerUrl: String?,
    val digest: String,
) {
    fun isCurrent(now: Long) = issuedAt <= now + 300 && now < expiresAt
}

internal interface DiscoveryCache {
    fun read(): String?
    fun write(envelope: String)
}

/** One complete signed payload is the durable version floor AND the route candidate set. */
internal class AtomicDiscoveryCache(private val file: File) : DiscoveryCache {
    private val atomic = AtomicFile(file)

    override fun read(): String? {
        if (!file.exists() && !File(file.path + ".bak").exists()) return null
        return atomic.openRead().use { input ->
            val bytes = ByteArray(64 * 1024 + 1)
            var size = 0
            while (size < bytes.size) {
                val count = input.read(bytes, size, bytes.size - size)
                if (count < 0) break
                size += count
            }
            check(size <= 64 * 1024) { "Discovery cache too large" }
            String(bytes, 0, size, Charsets.UTF_8)
        }
    }

    override fun write(envelope: String) {
        val stream = atomic.startWrite()
        try {
            stream.write(envelope.toByteArray(Charsets.UTF_8))
            atomic.finishWrite(stream)
        } catch (e: Exception) {
            atomic.failWrite(stream)
            throw e
        }
        // AtomicFile can report a sync/rename failure through Android logging.
        if (read() != envelope) throw IOException("Cannot persist discovery configuration")
    }
}

/** Two/three bounded HTTP requests; an unavailable mirror cannot hide a newer valid one. */
internal class SignedDiscovery(
    private val urls: List<String>,
    private val verifier: SignedManifestVerifier,
    private val cache: DiscoveryCache,
    private val now: () -> Long = { System.currentTimeMillis() / 1000 },
) {
    private val mutex = Mutex()
    @Volatile private var completedGeneration = 0L
    private var lastResult: VerifiedManifest? = null

    init {
        require(urls.isNotEmpty() && urls.size <= 3 && urls.distinct().size == urls.size)
        urls.forEach {
            val url = it.toHttpUrlOrNull() ?: error("Invalid discovery source")
            require(url.isHttps && url.username.isEmpty() && url.password.isEmpty() && url.fragment == null)
        }
    }

    suspend fun fetch(fetchJson: suspend (String, Long) -> JSONObject?): VerifiedManifest? {
        val observed = completedGeneration
        return mutex.withLock {
            currentCoroutineContext().ensureActive()
            if (observed != completedGeneration) return@withLock lastResult?.takeIf { it.isCurrent(now()) }
            // A corrupt cache must not silently reset the durable version floor.
            val previous = cache.read()?.let { verifier.verify(JSONObject(it)) }
            val candidates = coroutineScope {
                urls.map { url -> async {
                    try {
                        fetchJson(url, 5_000)?.let(verifier::verify)
                    } catch (e: CancellationException) { throw e }
                    catch (e: Exception) {
                        Timber.w("SignedDiscovery: source rejected (%s)", e.javaClass.simpleName)
                        null
                    }
                } }.awaitAll().filterNotNull()
            }
            currentCoroutineContext().ensureActive()
            val eligible = candidates.filter { candidate ->
                candidate.isCurrent(now()) && (previous == null || candidate.version > previous.version ||
                    (candidate.version == previous.version && candidate.digest == previous.digest))
            }
            // A publisher reusing a version for different payloads must not choose a random winner.
            val winner = eligible.groupBy { it.version }.values
                .filter { group -> group.map { it.digest }.distinct().size == 1 }
                .map { it.first() }.maxByOrNull { it.version }
            val selected = winner ?: previous?.takeIf { it.isCurrent(now()) }
            if (selected != null && selected.envelope != previous?.envelope) {
                currentCoroutineContext().ensureActive()
                cache.write(selected.envelope)
            }
            lastResult = selected
            completedGeneration++
            selected
        }
    }
}
