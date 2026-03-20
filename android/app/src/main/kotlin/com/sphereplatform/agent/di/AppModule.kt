package com.sphereplatform.agent.di

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.Lazy
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.serialization.json.Json
import com.sphereplatform.agent.network.FallbackDns
import okhttp3.CertificatePinner
import okhttp3.ConnectionPool
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    /**
     * OkHttpClient with:
     * - Authorization interceptor (Bearer token from AuthTokenStore)
     * - Certificate pinning via [buildCertificatePinner]
     *
     * Certificate pins are loaded from `res/raw/pinned_certs.txt` at runtime
     * (one SHA-256 pin per line, e.g. "sha256/AAAA…=="). If the file is absent
     * or empty, pinning is skipped — allowing development builds to work without
     * a real certificate. **Production builds MUST include pinned_certs.txt.**
     *
     * Pin extraction:
     *   openssl s_client -connect your-server.com:443 | \
     *     openssl x509 -pubkey -noout | \
     *     openssl pkey -pubin -outform der | \
     *     openssl dgst -sha256 -binary | base64
     */
    @Provides
    @Singleton
    fun provideOkHttpClient(
        lazyAuthStore: Lazy<AuthTokenStore>,
        @ApplicationContext ctx: Context,
    ): OkHttpClient {
        val builder = OkHttpClient.Builder()
            // FIX DNS: На эмуляторах (LDPlayer/Nox/MEmu) системный DNS часто
            // не резолвит внешние домены. FallbackDns пробует Google/Cloudflare
            // при неудаче системного резолвера. Zero overhead при рабочем DNS.
            .dns(FallbackDns())
            // FIX AUDIT-1.1: readTimeout=60s вместо бесконечного.
            // OkHttp WS ping (15s) + readTimeout(60s) = детектирование мёртвого
            // соединения за ~60с. Раньше при readTimeout=0 зависшие WS жили часами.
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            // FIX AUDIT-1.1: Один idle connection, 30s keep-alive.
            // Агент использует только одно WS-соединение, лишние TCP в пуле — waste.
            .connectionPool(ConnectionPool(1, 30, TimeUnit.SECONDS))
            // FIX-PING: WebSocket-level RFC 6455 ping каждые 15 секунд.
            // Cloudflare/nginx прозрачно пропускают WS ping/pong фреймы.
            // Это держит TCP-соединение живым через все прокси и NAT,
            // а также быстро детектирует мёртвые соединения (OkHttp закроет WS
            // если pong не придёт в течение readTimeout, который у нас infinite →
            // значит при потере связи WS умрёт по TCP keepalive/OS timeout).
            .pingInterval(15, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val token = lazyAuthStore.get().getToken()
                val request = if (token != null) {
                    chain.request().newBuilder()
                        .addHeader("Authorization", "Bearer $token")
                        .build()
                } else {
                    chain.request()
                }
                chain.proceed(request)
            }

        // Certificate pinning — loaded from res/raw/pinned_certs.txt
        buildCertificatePinner(ctx, lazyAuthStore.get())?.let { pinner ->
            builder.certificatePinner(pinner)
        }

        return builder.build()
    }

    /**
     * Builds a [CertificatePinner] from `res/raw/pinned_certs.txt`.
     *
     * File format (one pin per line):
     *   sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
     *
     * The host pattern is derived from the server URL stored in [AuthTokenStore].
     * Returns null if no pins file is present or the server URL is not set yet.
     */
    private fun buildCertificatePinner(ctx: Context, authStore: AuthTokenStore): CertificatePinner? {
        val serverUrl = authStore.getServerUrl().takeIf { it.isNotEmpty() } ?: return null
        val host = runCatching { java.net.URI(serverUrl).host }.getOrNull() ?: return null

        val resId = ctx.resources.getIdentifier("pinned_certs", "raw", ctx.packageName)
        if (resId == 0) return null  // File not present — skip pinning in dev builds

        val pins = ctx.resources.openRawResource(resId).bufferedReader()
            .readLines()
            .map { it.trim() }
            .filter { it.startsWith("sha256/") }

        if (pins.isEmpty()) return null

        return CertificatePinner.Builder()
            .apply { pins.forEach { add(host, it) } }
            .build()
    }

    @Provides
    @Singleton
    fun provideJsonParser(): Json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        isLenient = true
    }

    @Provides
    @Singleton
    fun providePreferences(@ApplicationContext ctx: Context): EncryptedSharedPreferences {
        val masterKey = MasterKey.Builder(ctx)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            ctx,
            "sphere_prefs",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        ) as EncryptedSharedPreferences
    }

    @Provides
    @Singleton
    fun provideCoroutineScope(): CoroutineScope =
        CoroutineScope(SupervisorJob() + Dispatchers.Default)
}
