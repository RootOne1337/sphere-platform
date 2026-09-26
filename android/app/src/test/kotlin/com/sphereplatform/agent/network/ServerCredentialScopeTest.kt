package com.sphereplatform.agent.network

import android.content.Context
import com.sphereplatform.agent.di.AppModule
import com.sphereplatform.agent.store.AuthTokenStore
import dagger.Lazy
import io.mockk.*
import okhttp3.Interceptor
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.junit.Assert.*
import org.junit.Test

class ServerCredentialScopeTest {
    private val auth = mockk<AuthTokenStore> {
        every { getToken() } returns "isolated-token"
        every { getServerUrl() } returns "https://management.example.invalid"
    }
    private val lazyAuth = mockk<Lazy<AuthTokenStore>> { every { get() } returns auth }
    private val context = mockk<Context>(relaxed = true)

    private fun requestThroughInterceptors(
        url: String,
        authorization: String? = null,
        enrollmentKey: String? = null,
        method: String = "GET",
    ): Request {
        val client = AppModule.provideOkHttpClient(lazyAuth, context)
        var request = Request.Builder().url(url).apply {
            authorization?.let { header("Authorization", it) }
            enrollmentKey?.let { header("X-API-Key", it) }
            if (method == "POST") post(ByteArray(0).toRequestBody())
        }.build()
        for (interceptor in client.interceptors + client.networkInterceptors) {
            val chain = mockk<Interceptor.Chain>()
            every { chain.request() } answers { request }
            every { chain.proceed(any()) } answers {
                request = firstArg()
                mockk<Response>(relaxed = true)
            }
            interceptor.intercept(chain)
        }
        return request
    }

    @Test fun externalDagRequestDoesNotReceiveDeviceCredential() {
        assertNull(requestThroughInterceptors("https://external.example.invalid/action").header("Authorization"))
    }

    @Test fun managementRequestReceivesOneAuthorizationHeader() {
        val request = requestThroughInterceptors("https://management.example.invalid/api/v1/devices/me")
        assertEquals(listOf("Bearer isolated-token"), request.headers.values("Authorization"))
    }

    @Test fun cloneEnrollmentDoesNotReceiveCopiedDeviceBearer() {
        val request = requestThroughInterceptors(
            "https://management.example.invalid/api/v1/devices/register",
            enrollmentKey = "scoped-enrollment-key",
            method = "POST",
        )
        assertNull("Enrollment is authenticated by its scoped X-API-Key, not a copied device token",
            request.header("Authorization"))
        assertEquals("scoped-enrollment-key", request.header("X-API-Key"))
    }

    @Test fun differentPortIsDifferentOrigin() {
        assertNull(requestThroughInterceptors("https://management.example.invalid:444/action").header("Authorization"))
    }

    @Test fun redirectedPlatformCredentialIsRemoved() {
        assertNull(requestThroughInterceptors("https://external.example.invalid/action", "Bearer isolated-token").header("Authorization"))
    }
}
