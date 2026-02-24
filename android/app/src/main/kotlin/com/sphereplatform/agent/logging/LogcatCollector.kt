package com.sphereplatform.agent.logging

import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * LogcatCollector — захват системного logcat по требованию.
 *
 * Используется:
 *  - командой REQUEST_LOGS / UPLOAD_LOGCAT из CommandHandler
 *  - LogUploadWorker для периодического сбора системных событий
 *
 * Требует разрешения READ_LOGS (android:protectionLevel="signature|privileged"),
 * которое на debug/enterprise-signed APK разрешается через adb:
 *   adb shell pm grant com.sphereplatform.agent android.permission.READ_LOGS
 * На Enterprise MDM-устройствах предоставляется через managed config / DPC.
 */
@Singleton
class LogcatCollector @Inject constructor() {

    companion object {
        private val SPHERE_TAGS = listOf(
            "SphereAgent", "SphereWS", "DagRunner", "OtaUpdate",
            "VpnManager", "CmdHandler", "LogUploadW", "UpdateCheckW",
            "ZeroTouch", "NetChange",
        )
    }

    /**
     * Собирает logcat-строки.
     *
     * @param lines  max lines to capture
     * @param tags   if non-null, фильтровать по этим тагам (all others silenced)
     * @return logcat output as String, или сообщение об ошибке
     */
    fun collect(lines: Int = 500, tags: List<String>? = null): String = runCatching {
        val cmd = buildList<String> {
            add("logcat")
            add("-d")                   // dump buffer (non-blocking)
            add("-v")
            add("threadtime")           // timestamp + tid
            add("-t")
            add(lines.coerceIn(1, 5000).toString())
            if (!tags.isNullOrEmpty()) {
                add("*:S")             // silence all by default
                tags.forEach { add("$it:V") }
            }
        }
        val process = ProcessBuilder(cmd)
            .redirectErrorStream(true)
            .start()
        val output = process.inputStream.bufferedReader(Charsets.UTF_8).readText()
        process.waitFor()
        output
    }.getOrElse { e ->
        val msg = "LogcatCollector: failed to read logcat — ${e.message}"
        Timber.w(e, msg)
        msg
    }

    /**
     * Только теги Sphere-агента (самые полезные для отладки приложения).
     */
    fun collectSphereOnly(lines: Int = 1000): String = collect(lines, SPHERE_TAGS)

    /**
     * Полный системный logcat (для диагностики взаимодействия ОС/агент).
     */
    fun collectSystemFull(lines: Int = 2000): String = collect(lines, tags = null)
}
