package com.sphereplatform.agent.root

import android.content.Context
import android.os.Build
import timber.log.Timber
import java.util.concurrent.TimeUnit

/**
 * Optional recovery help for rooted, owner-managed Android devices.
 *
 * Normal boot recovery remains Android-managed through BootReceiver,
 * JobScheduler, and WorkManager. This helper only adjusts this package's
 * background policy. It never starts an unmanaged daemon or changes
 * SELinux mode, remounts system partitions, edits init files, or copies the APK
 * into a privileged system directory.
 */
object RootAutoStart {
    @Volatile private var rootChecked = false
    @Volatile private var rootAvailable = false

    private const val DIAG_FILE = "/data/local/tmp/sphere_diag.txt"

    /** Returns only package-scoped commands; pure so tests can audit the root policy. */
    internal fun rootSetupCommands(packageName: String, apiLevel: Int): List<String> {
        validatePackageName(packageName)
        return buildList {
            add("dumpsys deviceidle whitelist +$packageName")
            add("cmd appops set $packageName RUN_IN_BACKGROUND allow")
            add("cmd appops set $packageName RUN_ANY_IN_BACKGROUND allow")
            if (apiLevel >= Build.VERSION_CODES.TIRAMISU) {
                add("pm grant $packageName android.permission.POST_NOTIFICATIONS")
            }
        }
    }

    /**
     * Runs once when the APK process starts. Failures are reported per operation;
     * the standard Android recovery path remains active if root is unavailable.
     */
    fun configure(context: Context) {
        if (!hasRoot()) {
            Timber.d("RootAutoStart: root unavailable; using Android-managed recovery")
            return
        }
        val packageName = context.packageName
        if (!isValidPackageName(packageName)) {
            Timber.e("RootAutoStart: rejected unexpected package name")
            return
        }

        auditLegacyRootState()
        execRoot("echo '[CONFIGURE] safe package-scoped root recovery' >> $DIAG_FILE")
        val commands = rootSetupCommands(packageName, Build.VERSION.SDK_INT)
        var succeeded = 0
        commands.forEach { command -> if (execRoot(command)) succeeded++ }
        Timber.i(
            "RootAutoStart: package-scoped setup %d/%d",
            succeeded,
            commands.size,
        )
    }

    /** Detects earlier releases' persistent system changes but never rewrites them. */
    private fun auditLegacyRootState() {
        val command = """
            printf 'selinux='; getenforce 2>/dev/null
            [ -f /data/local/tmp/sphere_startup.sh ] && echo legacy:data_startup
            grep -qF '/data/local/tmp/sphere_startup.sh' /system/etc/init/hw/init.rc /init.rc /system/etc/init/hw/init.target.rc 2>/dev/null && echo legacy:init_hook
            for f in /system/etc/init/sphere_autostart.rc /vendor/etc/init/sphere_autostart.rc /system/etc/init.d/99sphere /data/adb/service.d/99sphere /system/priv-app/SphereAgent/base.apk; do
              [ -f "${'$'}f" ] && echo legacy:system_hook
            done
        """.trimIndent()
        val output = readRootOutput(command) ?: return
        if (output.contains("legacy:") || output.contains("selinux=Permissive")) {
            Timber.w("RootAutoStart: legacy system-level startup state detected; left unchanged for safe manual review")
        }
    }

    fun hasRoot(): Boolean {
        if (rootChecked) return rootAvailable
        rootAvailable = try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "id"))
            val completed = process.waitFor(5, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                false
            } else if (process.exitValue() == 0) {
                process.inputStream.bufferedReader().use { it.readText() }.contains("uid=0")
            } else {
                false
            }
        } catch (_: Exception) {
            false
        }
        rootChecked = true
        Timber.d("RootAutoStart: root %s", if (rootAvailable) "available" else "unavailable")
        return rootAvailable
    }

    private fun execRoot(command: String): Boolean {
        return try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "$command >/dev/null 2>&1"))
            if (!process.waitFor(10, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: package-scoped operation timed out")
                false
            } else {
                val success = process.exitValue() == 0
                if (!success) Timber.w("RootAutoStart: package-scoped operation failed (exit=%d)", process.exitValue())
                success
            }
        } catch (error: Exception) {
            Timber.w(error, "RootAutoStart: package-scoped operation failed")
            false
        }
    }

    private fun readRootOutput(command: String): String? {
        return try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
            if (!process.waitFor(5, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                return null
            }
            process.inputStream.bufferedReader().use { it.readText().take(1024) }
        } catch (error: Exception) {
            Timber.d("RootAutoStart: legacy state probe unavailable (%s)", error.javaClass.simpleName)
            null
        }
    }

    private fun validatePackageName(packageName: String) {
        require(isValidPackageName(packageName)) { "Invalid Android package name" }
    }

    private fun isValidPackageName(packageName: String): Boolean =
        packageName.matches(Regex("[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)+"))
}
