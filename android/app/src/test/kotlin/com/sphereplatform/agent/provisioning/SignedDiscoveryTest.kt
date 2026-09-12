package com.sphereplatform.agent.provisioning

import com.sphereplatform.agent.BuildConfig
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.io.IOException
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [26], manifest = Config.NONE)
class SignedDiscoveryTest {
    companion object {
        private val pair = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()
        private const val installation = "04b8c5d2-c28e-4d12-a687-b3e211a9b6c7"
        private const val time = 1_800_000_000L
        private const val first = "https://config-a.invalid/agent.json"
        private const val second = "https://config-b.invalid/agent.json"
    }

    private fun payload(version: Long = 1, host: String = "https://new-route.invalid") = JSONObject()
        .put("schema_version", 1).put("installation_id", installation).put("config_version", version)
        .put("issued_at", time - 60).put("expires_at", time + 3600).put("server_url", host)

    private fun signed(data: JSONObject = payload()): JSONObject {
        val bytes = data.toString().toByteArray(Charsets.UTF_8)
        val signature = Signature.getInstance("SHA256withRSA").apply { initSign(pair.private); update(bytes) }.sign()
        return JSONObject().put("key_id", "test-key")
            .put("payload", Base64.getEncoder().encodeToString(bytes))
            .put("signature", Base64.getEncoder().encodeToString(signature))
    }

    private fun verifier() = SignedManifestVerifier(installation,
        mapOf("test-key" to Base64.getEncoder().encodeToString(pair.public.encoded)))

    private class MemoryCache : DiscoveryCache {
        var value: String? = null
        var writes = 0
        var failWrite = false
        override fun read() = value
        override fun write(envelope: String) {
            if (failWrite) throw IOException("isolated disk failure")
            value = envelope
            writes++
        }
    }

    private fun discovery(cache: DiscoveryCache, clock: () -> Long = { time }) =
        SignedDiscovery(listOf(first, second), verifier(), cache, clock)

    @Test fun `RSA verification and signed bytes work at minimum SDK 26`() {
        assertEquals("https://new-route.invalid", verifier().verify(signed()).serverUrl)
        val tampered = signed().put("payload", Base64.getEncoder().encodeToString(payload(2).toString().toByteArray()))
        assertThrows(Exception::class.java) { verifier().verify(tampered) }
    }

    @Test fun `Python signer vector verifies with Android wire format`() {
        val public = javaClass.getResource("/discovery/public-key.txt")!!.readText().trim()
        val document = javaClass.getResource("/discovery/signed-v1.json")!!.readText()
        val result = SignedManifestVerifier(installation, mapOf("test-key" to public)).verify(JSONObject(document))
        assertEquals(7L, result.version)
        assertEquals("https://primary.invalid", result.serverUrl)
    }

    @Test fun `retired fallback is absent from signed route set`() {
        val result = verifier().verify(signed(payload().put("fallback_server_url", JSONObject.NULL)))
        assertNull(result.fallbackServerUrl)
    }

    @Test fun `wrong key and installation and algorithm substitution are rejected`() {
        for (document in listOf(signed().put("key_id", "untrusted"),
            signed(payload().put("installation_id", UUID.randomUUID().toString())),
            signed().put("alg", "none"))) {
            assertThrows(Exception::class.java) { verifier().verify(document) }
        }
    }

    @Test fun `signed schema rejects coercion credentials unsafe routes and unknown fields`() {
        val bad = listOf(payload().put("config_version", true), payload().put("config_version", "1"),
            payload().put("config_version", 1.5), payload(0), payload().put("schema_version", 2),
            payload().put("enrollment_api_key", "must-never-be-public"),
            payload().put("expires_at", time - 120), payload(host = "http://cleartext.invalid"),
            payload(host = "https://user:password@host.invalid"), payload(host = "https://host.invalid?token=x"),
            payload(host = "https://host.invalid/path"), payload().put("fallback_server_url", "ftp://bad.invalid"))
        for (data in bad) assertThrows(data.toString(), Exception::class.java) { verifier().verify(signed(data)) }
    }

    @Test fun `newer mirror wins regardless of primary order`() = runBlocking {
        for (newerFirst in listOf(false, true)) {
            val cache = MemoryCache()
            val found = discovery(cache).fetch { url, _ -> signed(payload(if ((url == first) == newerFirst) 9 else 2)) }
            assertEquals(9L, found?.version)
            assertEquals(9L, verifier().verify(JSONObject(cache.value!!)).version)
        }
    }

    @Test fun `invalid primary does not prevent valid mirror`() = runBlocking {
        val cache = MemoryCache()
        val result = discovery(cache).fetch { url, _ ->
            if (url == first) JSONObject("{\"error\":\"unavailable\"}") else signed()
        }
        assertEquals(1L, result?.version)
        assertEquals(1, cache.writes)
    }

    @Test fun `expired and future manifests cannot migrate routes`() = runBlocking {
        for (data in listOf(payload().put("expires_at", time), payload().put("issued_at", time + 301))) {
            val cache = MemoryCache()
            assertNull(discovery(cache).fetch { _, _ -> signed(data) })
            assertEquals(0, cache.writes)
        }
    }

    @Test fun `reconstructed client retains floor and cached routes during complete config outage`() = runBlocking {
        val file = File(RuntimeEnvironment.getApplication().filesDir, UUID.randomUUID().toString())
        try {
            val firstRun = discovery(AtomicDiscoveryCache(file))
            assertEquals(7L, firstRun.fetch { _, _ -> signed(payload(7)) }?.version)
            assertEquals(7L, discovery(AtomicDiscoveryCache(file)).fetch { _, _ -> null }?.version)
            assertEquals(7L, discovery(AtomicDiscoveryCache(file)).fetch { _, _ -> signed(payload(3)) }?.version)
            assertEquals(7L, verifier().verify(JSONObject(AtomicDiscoveryCache(file).read()!!)).version)
        } finally { file.delete() }
    }

    @Test fun `same version with different payload cannot replace cached configuration`() = runBlocking {
        val cache = MemoryCache()
        discovery(cache).fetch { _, _ -> signed(payload(7)) }
        val after = discovery(cache).fetch { _, _ -> signed(payload(7, "https://changed.invalid")) }
        assertEquals("https://new-route.invalid", after?.serverUrl)
        assertEquals(1, cache.writes)
    }

    @Test fun `conflicting mirror versions do not select a random route`() = runBlocking {
        val cache = MemoryCache()
        assertNull(discovery(cache).fetch { url, _ -> signed(payload(7,
            if (url == first) "https://a.invalid" else "https://b.invalid")) })
        assertNull(cache.value)
    }

    @Test fun `cache write failure does not return unpersisted new routes`() = runBlocking {
        val cache = MemoryCache()
        discovery(cache).fetch { _, _ -> signed(payload(3)) }
        val previous = cache.value
        cache.failWrite = true
        try {
            discovery(cache).fetch { _, _ -> signed(payload(4)) }
            fail("Failed cache commit must propagate")
        } catch (_: IOException) { }
        assertEquals(previous, cache.value)
    }

    @Test fun `corrupt cache cannot reset floor and accept an older document`() = runBlocking {
        val cache = MemoryCache().apply { value = "broken" }
        val requests = AtomicInteger()
        try {
            discovery(cache).fetch { _, _ -> requests.incrementAndGet(); signed() }
            fail("Corrupt durable state requires operator diagnosis")
        } catch (_: Exception) { }
        assertEquals(0, requests.get())
        assertEquals("broken", cache.value)
    }

    @Test fun `cancellation stops mirrors and prevents late persistence`() = runBlocking {
        val cache = MemoryCache()
        val entered = CompletableDeferred<Unit>()
        val cancelled = AtomicInteger()
        val lookup = launch { discovery(cache).fetch { _, _ ->
            entered.complete(Unit)
            try { awaitCancellation() } finally { cancelled.incrementAndGet() }
        } }
        entered.await()
        lookup.cancelAndJoin()
        assertTrue(cancelled.get() > 0)
        assertEquals(0, cache.writes)
    }

    @Test fun `concurrent callers share one mirror cycle`() = runBlocking {
        val cache = MemoryCache()
        val subject = discovery(cache)
        val release = CompletableDeferred<Unit>()
        val calls = AtomicInteger()
        val jobs = List(32) { async(start = CoroutineStart.UNDISPATCHED) {
            subject.fetch { _, _ -> calls.incrementAndGet(); release.await(); signed() }
        } }
        yield()
        release.complete(Unit)
        assertTrue(jobs.awaitAll().all { it?.version == 1L })
        assertEquals(2, calls.get())
        assertEquals(1, cache.writes)
    }

    @Test fun `signed initial discovery binds local key to entirely new routes without sending it to mirrors`() = runBlocking {
        val requests = CopyOnWriteArrayList<Request>()
        val document = signed(payload().put("fallback_server_url", "https://new-backup.invalid"))
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            requests.add(chain.request())
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("isolated")
                .body(document.toString().toResponseBody()).build()
        }.build()
        try {
            val provisioner = ZeroTouchProvisioner(RuntimeEnvironment.getApplication(), first,
                listOf(second), discovery(MemoryCache())) { client }
            val config = provisioner.discoverConfig()!!
            assertEquals("https://new-route.invalid", config.serverUrl)
            assertEquals("https://new-backup.invalid", config.fallbackServerUrl)
            assertEquals(BuildConfig.DEFAULT_API_KEY, config.apiKey)
            assertTrue(config.requiresRegistration)
            assertEquals(2, requests.size)
            assertTrue(requests.all { it.header("Authorization") == null && it.header("X-API-Key") == null })
        } finally { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
    }

    @Test fun `strict discovery never downgrades to unsigned document or baked route`() = runBlocking {
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("isolated")
                .body("""{"server_url":"${BuildConfig.DEFAULT_SERVER_URL}"}""".toResponseBody()).build()
        }.build()
        try {
            val provisioner = ZeroTouchProvisioner(RuntimeEnvironment.getApplication(), first,
                listOf(second), discovery(MemoryCache())) { client }
            assertNull(provisioner.discoverConfig())
        } finally { client.dispatcher.executorService.shutdown(); client.connectionPool.evictAll() }
    }

    @Test fun `discovery revalidates HTTP cache before reusing signed routes`() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setHeader("Cache-Control", "public, max-age=300")
            .setBody(signed(payload(1, "https://old-route.invalid")).toString()))
        server.enqueue(MockResponse().setHeader("Cache-Control", "public, max-age=300")
            .setBody(signed(payload(2, "https://replacement.invalid")).toString()))
        server.start()
        val directory = File(RuntimeEnvironment.getApplication().cacheDir, "http-${UUID.randomUUID()}")
        val httpCache = Cache(directory, 1024 * 1024)
        val client = OkHttpClient.Builder().cache(httpCache).addInterceptor { chain ->
            // Isolated loopback transport; production sources still require HTTPS.
            chain.proceed(chain.request().newBuilder().url(server.url("/agent.json")).build())
        }.build()
        try {
            val subject = SignedDiscovery(listOf(first), verifier(), MemoryCache()) { time }
            val provisioner = ZeroTouchProvisioner(RuntimeEnvironment.getApplication(), first,
                emptyList(), subject) { client }
            assertEquals("https://old-route.invalid", provisioner.fetchServerConfig()?.serverUrl)
            // A valid signature does not make the cached route the publisher's latest route.
            assertEquals("https://replacement.invalid", provisioner.fetchServerConfig()?.serverUrl)
            assertEquals(2, server.requestCount)
        } finally {
            client.dispatcher.executorService.shutdown()
            client.connectionPool.evictAll()
            httpCache.close()
            server.close()
        }
    }

    @Test fun `signed source leaves stale CDN cache bucket on next minute`() = runBlocking {
        val server = MockWebServer()
        server.enqueue(MockResponse().setHeader("Cache-Control", "public, max-age=300")
            .setBody(signed(payload(1, "https://old-route.invalid")).toString()))
        server.enqueue(MockResponse().setHeader("Cache-Control", "public, max-age=300")
            .setBody(signed(payload(2, "https://replacement.invalid")).toString()))
        server.start()
        val httpCache = Cache(File(RuntimeEnvironment.getApplication().cacheDir, "cdn-${UUID.randomUUID()}"), 1024 * 1024)
        val client = OkHttpClient.Builder().cache(httpCache).addInterceptor { chain ->
            // Model an intermediary that ignores request no-cache but keys by full URL.
            val target = server.url("/agent.json").newBuilder()
                .encodedQuery(chain.request().url.encodedQuery).build()
            chain.proceed(chain.request().newBuilder().url(target).removeHeader("Cache-Control").build())
        }.build()
        var clock = time
        try {
            val source = "$first?channel=pilot"
            val subject = SignedDiscovery(listOf(source), verifier(), MemoryCache()) { clock }
            val provisioner = ZeroTouchProvisioner(RuntimeEnvironment.getApplication(), source,
                emptyList(), subject) { client }
            assertEquals("https://old-route.invalid", provisioner.fetchServerConfig()?.serverUrl)
            assertEquals("https://old-route.invalid", provisioner.fetchServerConfig()?.serverUrl)
            assertEquals(1, server.requestCount) // Shared cache key within one minute.
            clock += 60
            assertEquals("https://replacement.invalid", provisioner.fetchServerConfig()?.serverUrl)
            assertEquals(2, server.requestCount)
            val firstRequest = server.takeRequest(1, TimeUnit.SECONDS)!!.requestUrl!!
            val nextRequest = server.takeRequest(1, TimeUnit.SECONDS)!!.requestUrl!!
            assertEquals("pilot", nextRequest.queryParameter("channel"))
            assertNotEquals(firstRequest.queryParameter("sphere_bootstrap_epoch"), nextRequest.queryParameter("sphere_bootstrap_epoch"))
        } finally {
            client.dispatcher.executorService.shutdown()
            client.connectionPool.evictAll()
            httpCache.close()
            server.close()
        }
    }

    @Test fun `stuck source has bounded deadline and cannot block successful mirror or write late`() = runBlocking {
        val release = CountDownLatch(1)
        val entered = CountDownLatch(1)
        val calls = CopyOnWriteArrayList<Call>()
        val cache = MemoryCache()
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            calls.add(chain.call())
            if (chain.request().url.host == "config-a.invalid") {
                entered.countDown()
                check(release.await(15, TimeUnit.SECONDS))
            }
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("isolated")
                .body(signed(payload(if (chain.request().url.host == "config-a.invalid") 99 else 7))
                    .toString().toResponseBody()).build()
        }.build()
        try {
            val provisioner = ZeroTouchProvisioner(RuntimeEnvironment.getApplication(), first,
                listOf(second), discovery(cache)) { client }
            val lookup = async(Dispatchers.Default) { provisioner.fetchServerConfig() }
            assertTrue(entered.await(3, TimeUnit.SECONDS))
            assertEquals("https://new-route.invalid", withTimeout(7_000) { lookup.await() }?.serverUrl)
            assertTrue(calls.first { it.request().url.host == "config-a.invalid" }.isCanceled())
            assertEquals(7L, verifier().verify(JSONObject(cache.value!!)).version)
        } finally {
            release.countDown()
            client.dispatcher.executorService.shutdown()
            assertTrue(client.dispatcher.executorService.awaitTermination(3, TimeUnit.SECONDS))
            client.connectionPool.evictAll()
        }
        assertEquals(1, cache.writes)
        assertEquals(7L, verifier().verify(JSONObject(cache.value!!)).version)
    }
}
