package com.sphereplatform.agent.ota

import android.app.Application
import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.content.pm.SigningInfo
import android.os.Build
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/** Execute the production verifier against platform metadata at both signature APIs. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [26, 28], manifest = Config.NONE, application = Application::class)
@Suppress("DEPRECATION")
class OtaApkVerifierTest {
    private val manager = mockk<PackageManager>()
    private val context = mockk<Context>()
    private val apk = File("/fixture/update.apk")
    private val payload = OtaUpdatePayload("https://management.test/update.apk", "next", "a".repeat(64), 101)
    private lateinit var installed: PackageInfo
    private lateinit var candidate: PackageInfo
    private val flags get() = if (Build.VERSION.SDK_INT >= 28)
                                 PackageManager.GET_SIGNING_CERTIFICATES or PackageManager.GET_SIGNATURES
                              else PackageManager.GET_SIGNATURES

    @Before fun setup() {
        every { context.packageName } returns "com.sphere.fixture"
        every { context.packageManager } returns manager
        installed = info(100, "current", listOf("owner"))
        candidate = info(101, "next", listOf("owner"))
        every { manager.getPackageInfo("com.sphere.fixture", flags) } answers { installed }
        every { manager.getPackageArchiveInfo(apk.absolutePath, flags) } answers { candidate }
    }

    private fun info(code: Int, name: String, certs: List<String>) = PackageInfo().also {
        it.packageName = context.packageName
        it.versionCode = code
        it.versionName = name
        it.applicationInfo = ApplicationInfo().also { application -> application.minSdkVersion = 26 }
        val signatures = certs.map { certificate -> Signature(certificate.toByteArray()) }.toTypedArray()
        if (Build.VERSION.SDK_INT >= 28) {
            it.signingInfo = mockk<SigningInfo>().also { signing ->
                every { signing.apkContentsSigners } returns signatures
            }
        } else it.signatures = signatures
    }

    private fun rejected(code: String) {
        val error = runCatching { OtaApkVerifier(context).verify(apk, payload) }.exceptionOrNull()
        assertTrue("Expected a stable artifact rejection, got $error", error is OtaArtifactRejectedException)
        assertEquals(code, error?.message)
    }

    @Test fun `matching package version SDK and signer are accepted`() {
        OtaApkVerifier(context).verify(apk, payload)
        verify(exactly = 1) { manager.getPackageArchiveInfo(apk.absolutePath, flags) }
        verify(exactly = 1) { manager.getPackageInfo("com.sphere.fixture", flags) }
    }

    @Test fun `unparseable file is rejected`() {
        every { manager.getPackageArchiveInfo(apk.absolutePath, flags) } returns null
        rejected("ota_archive_unreadable")
    }

    @Test fun `parser exceptions produce a bounded rejection code`() {
        every { manager.getPackageArchiveInfo(apk.absolutePath, flags) } throws IllegalStateException("private file path")
        rejected("ota_archive_unreadable")
    }

    @Test fun `other package cannot reach root side installation`() {
        candidate.packageName = "com.some.other.app"
        rejected("ota_package_mismatch")
        verify(exactly = 0) { manager.getPackageInfo(any<String>(), any<Int>()) }
    }

    @Test fun `catalog version code must exactly match archive`() {
        candidate.versionCode = 102
        rejected("ota_version_mismatch")
    }

    @Test fun `catalog version name must exactly match archive`() {
        candidate.versionName = "different"
        rejected("ota_version_mismatch")
    }

    @Test fun `unreported application metadata is rejected`() {
        candidate.applicationInfo = null
        rejected("ota_archive_unreadable")
    }

    @Test fun `unsupported minimum SDK is rejected`() {
        candidate.applicationInfo!!.minSdkVersion = Build.VERSION.SDK_INT + 1
        rejected("ota_sdk_unsupported")
    }

    @Test fun `equal installed version cannot be force reinstalled`() {
        installed.versionCode = 101
        rejected("ota_version_not_newer")
    }

    @Test fun `newer installed version cannot be downgraded`() {
        installed.versionCode = 102
        rejected("ota_version_not_newer")
    }

    @Test fun `missing installed package is an explicit rejection`() {
        every { manager.getPackageInfo("com.sphere.fixture", flags) } throws PackageManager.NameNotFoundException()
        rejected("ota_installed_package_unavailable")
    }

    @Test fun `candidate signature cannot be omitted`() {
        candidate = info(101, "next", emptyList())
        rejected("ota_signer_unavailable")
    }

    @Test fun `installed signature cannot be omitted`() {
        installed = info(100, "current", emptyList())
        rejected("ota_signer_unavailable")
    }

    @Test fun `unrelated signer is rejected`() {
        candidate = info(101, "next", listOf("attacker"))
        rejected("ota_signer_mismatch")
    }

    @Test fun `multi signer identity is independent of array ordering`() {
        installed = info(100, "current", listOf("first", "second"))
        candidate = info(101, "next", listOf("second", "first"))
        OtaApkVerifier(context).verify(apk, payload)
    }

    @Test fun `extra signer changes multi signer identity`() {
        candidate = info(101, "next", listOf("owner", "other"))
        rejected("ota_signer_mismatch")
    }

    @Test fun `a shared historical certificate cannot authorize a changed current signer`() {
        candidate = info(101, "next", listOf("changed"))
        if (Build.VERSION.SDK_INT >= 28) {
            every { candidate.signingInfo!!.signingCertificateHistory } returns arrayOf(Signature("owner".toByteArray()))
        }
        rejected("ota_signer_mismatch")
    }
}
