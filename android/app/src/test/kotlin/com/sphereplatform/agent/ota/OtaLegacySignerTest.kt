package com.sphereplatform.agent.ota

import android.app.Application
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.content.pm.SigningInfo
import io.mockk.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** PM is the certificate authority here; synthetic ZIPs test only the format gate. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
@Suppress("DEPRECATION")
class OtaLegacySignerTest {
    private val manager = mockk<PackageManager>()
    private val context = mockk<Context>()
    private val payload = OtaUpdatePayload("https://management.test/update.apk", "next", "a".repeat(64), 101)
    private lateinit var apk: File
    private lateinit var own: File
    private lateinit var candidate: PackageInfo
    private lateinit var installed: PackageInfo

    @Before fun setup() {
        apk = fixture(); own = fixture()
        every { context.packageName } returns "com.sphere.fixture"
        every { context.packageManager } returns manager
        every { context.applicationInfo } returns ApplicationInfo().also { it.sourceDir = own.absolutePath }
        candidate = info(101, "next"); installed = info(100, "current")
        every { manager.getPackageArchiveInfo(apk.absolutePath, any<Int>()) } answers { candidate }
        every { manager.getPackageInfo("com.sphere.fixture", any<Int>()) } answers { installed }
    }
    @After fun cleanup() { apk.delete(); own.delete(); unmockkAll() }
    private fun info(code: Int, name: String) = PackageInfo().also {
        it.packageName = "com.sphere.fixture"; it.versionCode = code; it.versionName = name
        it.applicationInfo = ApplicationInfo().also { app -> app.minSdkVersion = 26 }
        it.signatures = arrayOf(Signature("owner".toByteArray()))
        it.signingInfo = null
    }
    private fun rejected(code: String) {
        val error = runCatching { OtaApkVerifier(context).verify(apk, payload) }.exceptionOrNull()
        assertTrue(error is OtaArtifactRejectedException)
        assertEquals(code, error?.message)
    }
    @Test fun `OEM legacy certificates on v2-only APKs retain exact signer protection`() {
        OtaApkVerifier(context).verify(apk, payload)
        val flags = PackageManager.GET_SIGNING_CERTIFICATES or PackageManager.GET_SIGNATURES
        verify(exactly = 1) { manager.getPackageArchiveInfo(apk.absolutePath, flags) }
        verify(exactly = 1) { manager.getPackageInfo("com.sphere.fixture", flags) }
    }
    @Test fun `missing installed modern API can coexist with candidate current signer API`() {
        candidate.signingInfo = mockk<SigningInfo>().also {
            every { it.apkContentsSigners } returns arrayOf(Signature("owner".toByteArray()))
        }
        OtaApkVerifier(context).verify(apk, payload)
    }
    @Test fun `legacy API cannot authorize a different certificate`() {
        candidate.signatures = arrayOf(Signature("attacker".toByteArray()))
        rejected("ota_signer_mismatch")
    }
    @Test fun `empty legacy certificate set still fails closed`() {
        candidate.signatures = emptyArray(); rejected("ota_signer_unavailable")
    }
    @Test fun `modern current signer mismatch never downgrades to matching legacy history`() {
        candidate.signingInfo = mockk<SigningInfo>().also {
            every { it.apkContentsSigners } returns arrayOf(Signature("changed".toByteArray()))
        }
        rejected("ota_signer_mismatch")
    }
    @Test fun `present modern info with empty current signers never falls back`() {
        candidate.signingInfo = mockk<SigningInfo>().also { every { it.apkContentsSigners } returns emptyArray() }
        rejected("ota_signer_unavailable")
    }
    @Test fun `legacy candidate with rotation-capable or unknown signing block is rejected`() {
        for (id in listOf(0xf05368c0.toInt(), 0x1b93ad61, 0x12345678)) {
            apk.writeBytes(fixtureBytes(listOf(0x7109871a, id)))
            rejected("ota_signer_unavailable")
        }
    }
    @Test fun `legacy installed APK with rotation block is rejected`() {
        own.writeBytes(fixtureBytes(listOf(0x7109871a, 0xf05368c0.toInt())))
        rejected("ota_signer_unavailable")
    }
    @Test fun `unreadable installed archive cannot enable fallback`() {
        own.delete(); rejected("ota_signer_unavailable")
    }
    @Test fun `v2 format gate rejects unsigned duplicate malformed and overflowing blocks`() {
        val good = fixtureBytes(listOf(0x7109871a))
        for (bytes in listOf(byteArrayOf(), good.copyOf(30), fixtureBytes(emptyList()),
                            fixtureBytes(listOf(0x7109871a, 0x7109871a)),
                            good.clone().also { ByteBuffer.wrap(it).order(ByteOrder.LITTLE_ENDIAN).putLong(32, Long.MAX_VALUE) },
                            good.clone().also { it[it.size - 1] = 1 })) {
            apk.writeBytes(bytes); assertFalse(ApkV2OnlyPolicy.allows(apk))
        }
        apk.writeBytes(fixtureBytes(listOf(0x7109871a, 0x42726577)))
        assertTrue(ApkV2OnlyPolicy.allows(apk))
    }
    private fun fixture(): File = File.createTempFile("sphere-v2-policy", ".apk").also {
        it.writeBytes(fixtureBytes(listOf(0x7109871a)))
    }
    private fun fixtureBytes(ids: List<Int>): ByteArray {
        val pairBytes = ids.size * 13
        val blockSize = pairBytes + 24L
        val directory = 32 + blockSize.toInt() + 8
        return ByteBuffer.allocate(directory + 46 + 22).order(ByteOrder.LITTLE_ENDIAN).apply {
            putInt(0x04034b50); position(32); putLong(blockSize)
            ids.forEach { putLong(5); putInt(it); put(1) }
            putLong(blockSize); put("APK Sig Block 42".toByteArray(Charsets.US_ASCII))
            putInt(0x02014b50); position(directory + 46)
            putInt(0x06054b50); putShort(0); putShort(0); putShort(1); putShort(1)
            putInt(46); putInt(directory); putShort(0)
        }.array()
    }
}
