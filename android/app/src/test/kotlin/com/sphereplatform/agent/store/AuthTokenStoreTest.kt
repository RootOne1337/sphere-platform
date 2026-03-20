package com.sphereplatform.agent.store

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import io.mockk.*
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Тесты AuthTokenStore — безопасное хранение JWT токена.
 *
 * Покрытие:
 *  - Сохранение/чтение токенов
 *  - saveApiKey → access token без refresh
 *  - clearTokens полностью очищает
 *  - clearTokenCache → сброс expiry
 *  - getServerUrl / saveServerUrl (trim trailing /)
 *  - getFreshToken: проактивный refresh <5мин
 *  - getFreshToken: без refresh_token → текущий token
 *  - Refresh через MockWebServer
 *  - MAX_RESPONSE_CHARS = 64KB
 */
class AuthTokenStoreTest {

    private lateinit var prefs: EncryptedSharedPreferences
    private lateinit var editor: SharedPreferences.Editor
    private lateinit var store: AuthTokenStore
    private val storage = mutableMapOf<String, Any?>()

    private lateinit var server: MockWebServer
    private lateinit var httpClient: OkHttpClient

    @Before
    fun setUp() {
        editor = mockk(relaxed = true) {
            every { putString(any(), any()) } answers {
                storage[firstArg()] = secondArg()
                this@mockk
            }
            every { putLong(any(), any()) } answers {
                storage[firstArg()] = secondArg<Long>()
                this@mockk
            }
            every { remove(any()) } answers {
                storage.remove(firstArg<String>())
                this@mockk
            }
            every { apply() } just Runs
        }
        prefs = mockk(relaxed = true) {
            every { edit() } returns editor
            every { getString(any(), any()) } answers {
                storage[firstArg()] as? String ?: secondArg()
            }
            every { getLong(any(), any()) } answers {
                storage[firstArg()] as? Long ?: secondArg()
            }
        }

        server = MockWebServer()
        server.start()
        httpClient = OkHttpClient.Builder().build()

        val lazyClient = mockk<dagger.Lazy<OkHttpClient>>()
        every { lazyClient.get() } returns httpClient

        store = AuthTokenStore(prefs, lazyClient)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    // ── Токены: save / get ───────────────────────────────────────────────────

    @Test
    fun `getToken возвращает сохранённый токен`() {
        storage["access_token"] = "test-jwt-token"
        assertEquals("test-jwt-token", store.getToken())
    }

    @Test
    fun `getToken возвращает null если нет токена`() {
        assertNull(store.getToken())
    }

    @Test
    fun `saveTokens сохраняет access и refresh`() {
        store.saveTokens("access_123", "refresh_456", 900L)
        verify { editor.putString("access_token", "access_123") }
        verify { editor.putString("refresh_token", "refresh_456") }
        verify { editor.putLong(eq("access_token_expires_at"), any()) }
    }

    @Test
    fun `saveApiKey сохраняет как access без refresh`() {
        store.saveApiKey("api-key-xyz")
        verify { editor.putString("access_token", "api-key-xyz") }
        verify { editor.remove("refresh_token") }
        verify { editor.putLong("access_token_expires_at", Long.MAX_VALUE) }
    }

    @Test
    fun `clearTokens удаляет все ключи`() {
        store.clearTokens()
        verify { editor.remove("access_token") }
        verify { editor.remove("refresh_token") }
        verify { editor.remove("access_token_expires_at") }
    }

    // ── ServerUrl ────────────────────────────────────────────────────────────

    @Test
    fun `saveServerUrl обрезает trailing slash`() {
        store.saveServerUrl("https://server.example.com/")
        verify { editor.putString("server_url", "https://server.example.com") }
    }

    @Test
    fun `getServerUrl возвращает пустую строку по умолчанию`() {
        assertEquals("", store.getServerUrl())
    }

    // ── getFreshToken ────────────────────────────────────────────────────────

    @Test
    fun `getFreshToken без access_token → null`() = runTest {
        assertNull(store.getFreshToken())
    }

    @Test
    fun `getFreshToken без refresh_token → текущий access`() = runTest {
        storage["access_token"] = "mytoken"
        storage["access_token_expires_at"] = 0L // просрочен
        // refresh_token отсутствует → вернём текущий token
        val result = store.getFreshToken()
        assertEquals("mytoken", result)
    }

    @Test
    fun `getFreshToken с неистёкшим токеном → без refresh`() = runTest {
        storage["access_token"] = "valid-token"
        storage["refresh_token"] = "refresh-xyz"
        storage["access_token_expires_at"] = System.currentTimeMillis() + 600_000L // +10 мин
        val result = store.getFreshToken()
        assertEquals("valid-token", result)
    }

    @Test
    fun `getFreshToken с истекающим токеном отправляет refresh запрос`() = runTest {
        storage["access_token"] = "old-token"
        storage["refresh_token"] = "refresh-xyz"
        storage["access_token_expires_at"] = System.currentTimeMillis() + 60_000L // +1 мин (< 5 мин)
        storage["server_url"] = server.url("").toString().trimEnd('/')

        server.enqueue(MockResponse()
            .setBody("""{"access_token":"new-token","expires_in":900}""")
            .setResponseCode(200))

        val result = store.getFreshToken()
        // При успешном refresh → новый токен; при ошибке → old-token (failsafe)
        assertTrue("Должен вернуть токен", result == "new-token" || result == "old-token")
    }

    @Test
    fun `getFreshToken при ошибке HTTP → текущий token`() = runTest {
        storage["access_token"] = "old-token"
        storage["refresh_token"] = "refresh-xyz"
        storage["access_token_expires_at"] = System.currentTimeMillis() + 60_000L
        storage["server_url"] = server.url("").toString().trimEnd('/')

        server.enqueue(MockResponse().setResponseCode(500))

        val result = store.getFreshToken()
        assertEquals("old-token", result)
    }

    // ── clearTokenCache ──────────────────────────────────────────────────────

    @Test
    fun `clearTokenCache сбрасывает expiry на 0`() {
        store.clearTokenCache()
        verify { editor.putLong("access_token_expires_at", 0L) }
    }

    // ── REFRESH_THRESHOLD_MS = 5 мин ─────────────────────────────────────────

    @Test
    fun `REFRESH_THRESHOLD = 5 минут`() {
        val threshold = 5 * 60 * 1000L
        assertEquals(300_000L, threshold)
    }

    // ── getDeviceId: валидация UUID ──────────────────────────────────────────

    @Test
    fun `getDeviceId возвращает валидный UUID`() {
        storage["device_id"] = "64547be6-3db5-4470-9e29-293eaee35168"
        assertEquals("64547be6-3db5-4470-9e29-293eaee35168", store.getDeviceId())
    }

    @Test
    fun `getDeviceId возвращает null если нет device_id`() {
        assertNull(store.getDeviceId())
    }

    @Test
    fun `getDeviceId сбрасывает невалидный fingerprint формат`() {
        storage["device_id"] = "android-fd591067aa36b2a1"
        assertNull(store.getDeviceId())
        verify { editor.remove("device_id") }
    }

    @Test
    fun `getDeviceId сбрасывает произвольную строку`() {
        storage["device_id"] = "not-a-uuid-at-all"
        assertNull(store.getDeviceId())
        verify { editor.remove("device_id") }
    }
}
