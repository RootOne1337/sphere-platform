package com.sphereplatform.agent.ota

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import java.io.File
import java.security.MessageDigest

/** Stable, bounded diagnostic code; never includes APK paths or server data. */
class OtaArtifactRejectedException(val failureCode: String) : IllegalArgumentException(failureCode)

/** Inspect the actual downloaded APK before root or PackageInstaller gets access. */
@Suppress("DEPRECATION")
class OtaApkVerifier(private val context: Context) {
    fun verify(apk: File, payload: OtaUpdatePayload) {
        val manager = context.packageManager
        val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES
                    else PackageManager.GET_SIGNATURES
        @Suppress("DEPRECATION")
        val candidate = try {
            manager.getPackageArchiveInfo(apk.absolutePath, flags)
        } catch (_: RuntimeException) {
            reject("ota_archive_unreadable")
        } ?: reject("ota_archive_unreadable")
        if (candidate.packageName != context.packageName) reject("ota_package_mismatch")
        if (version(candidate) != payload.version_code.toLong()
            || candidate.versionName != payload.version) reject("ota_version_mismatch")
        val application = candidate.applicationInfo ?: reject("ota_archive_unreadable")
        if (application.minSdkVersion > Build.VERSION.SDK_INT) reject("ota_sdk_unsupported")
        @Suppress("DEPRECATION")
        val installed = try {
            manager.getPackageInfo(context.packageName, flags)
        } catch (_: PackageManager.NameNotFoundException) {
            reject("ota_installed_package_unavailable")
        }
        if (version(candidate) <= version(installed)) reject("ota_version_not_newer")
        // Exact current signer set is deliberate. An ancestor shared by two
        // different descendants is insufficient. Key rotation needs a separate
        // tested promotion policy; the OS installer remains final authority.
        if (signers(candidate) != signers(installed)) reject("ota_signer_mismatch")
    }

    @Suppress("DEPRECATION")
    private fun version(info: PackageInfo): Long =
        if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()

    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo): Set<String> {
        val certificates = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners
                           else info.signatures
        if (certificates.isNullOrEmpty()) reject("ota_signer_unavailable")
        return certificates.map { signature ->
            MessageDigest.getInstance("SHA-256").digest(signature.toByteArray())
                .joinToString("") { "%02x".format(it) }
        }.toSet()
    }

    private fun reject(code: String): Nothing = throw OtaArtifactRejectedException(code)
}
