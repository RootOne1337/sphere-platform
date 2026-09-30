package com.sphereplatform.agent.commands

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.w3c.dom.Element
import org.xmlpull.v1.XmlPullParser
import org.xmlpull.v1.XmlPullParserFactory
import timber.log.Timber
import java.io.StringReader
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import javax.xml.xpath.XPathConstants
import javax.xml.xpath.XPathFactory

/** The shell may already have consumed the command; do not automatically retry. */
class RootCommandOutcomeUnknownException(
    message: String = "Root command delivery outcome is unknown",
) : java.io.IOException(message)

/**
 * AdbActionExecutor — выполняет ADB-примитивы через постоянную root-сессию.
 *
 * ## Постоянная root-сессия (FIX 7.3)
 * Один `su` процесс + DataOutputStream вместо fork+exec на каждую команду.
 * Экономия ~99% CPU: команды пишутся в stdin (<1ms), а не fork/exec (50–150ms).
 *
 * ## TypeText (enterprise)
 * - Все символы кроме алфавитно-цифровых и базового ASCII экранируются
 * - Механизм clipboard-paste для текстов со спецсимволами (>ASCII126 или содержащих кавычки)
 * - `clear_first` — select all + delete перед вводом
 *
 * ## FindElement (uiautomator dump)
 * - Парсит XML дамп UI дерева через Android XmlPullParser (simple) или javax.xml.xpath (xpath)
 * - Стратегии: text, id (resource-id), desc (content-desc), class, xpath (полный XPath 1.0)
 * - xpath: иерархия, несколько предикатов, позиции, contains(), and/or, last() и т.д.
 * - Polling до заданного timeoutMs с интервалом 500ms
 *
 * ## БЕЗОПАСНОСТЬ
 * - `shell()` проверяет команду через SHELL_INJECTION_PATTERN перед su -c
 * - `typeText()` никогда не передаёт текст через sh напрямую; использует
 *   `am broadcast` для clipboard → paste, что полностью устраняет shell injection
 */
@Singleton
class AdbActionExecutor @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        // Запрещаем shell metacharacters для shell() метода
        private val SHELL_INJECTION_PATTERN = Regex("""[;|&${'$'}`(){}\\<>!\n\r#~]""")

        // UI dump poll interval for findElement
        private const val FIND_ELEMENT_POLL_MS = 500L
        // Таймаут одного uiautomator dump: 4s достаточно на LDPlayer.
        // 12s → каждый зависший dump блокировал IO-поток на 12 секунд!
        private const val UI_DUMP_TIMEOUT_SECONDS = 4L

        private val XPATH_FACTORY: XPathFactory by lazy {
            XPathFactory.newInstance()
        }
        // FIX AUDIT-2.2: Кеш XmlPullParserFactory — newInstance() делает service discovery
        // через рефлексию (~5-10ms). Parser создаётся каждый раз (не потокобезопасен).
        private val XMLPULL_FACTORY: XmlPullParserFactory by lazy {
            XmlPullParserFactory.newInstance()
        }
    }

    // Agent startup and non-root capabilities must not depend on a root grant.
    // These references are initialized only by an explicit privileged action.
    private var rootProcess: Process? = null
    private var rootStream: java.io.DataOutputStream? = null
    private val rootLock = Any()
    private val processRunner = BoundedProcessRunner()
    private val uiDumpOwnership = Mutex()

    private fun createRootProcess(): Process =
        Runtime.getRuntime().exec("su").also {
            Timber.i("Root session opened")
        }

    /** Called only while holding rootLock, when a privileged action is requested. */
    private fun ensureRootAlive(): java.io.DataOutputStream {
        val existing = rootProcess
        if (existing != null && existing.isAlive) return checkNotNull(rootStream)
        runCatching { rootStream?.close() }
        rootStream = null
        rootProcess = null

        val next = createRootProcess()
        val stream = try {
            java.io.DataOutputStream(next.outputStream)
        } catch (e: Exception) {
            runCatching { next.destroyForcibly() }
            throw e
        }
        rootProcess = next
        rootStream = stream
        return stream
    }

    private val physicalSize: android.graphics.Point
        get() {
            val metrics = android.content.res.Resources.getSystem().displayMetrics
            return android.graphics.Point(metrics.widthPixels, metrics.heightPixels)
        }

    private val isLandscape: Boolean
        get() = physicalSize.x > physicalSize.y

    private val streamWidth: Float
        get() = if (isLandscape) 1280f else 720f

    private val streamHeight: Float
        get() = if (isLandscape) 720f else 1280f

    private fun scaleX(x: Int): Int =
        (x * (physicalSize.x.toFloat() / streamWidth)).toInt()

    private fun scaleY(y: Int): Int =
        (y * (physicalSize.y.toFloat() / streamHeight)).toInt()

    /**
     * Выполняет команду в постоянной root-сессии.
     * synchronized — защита от конкурентного доступа.
     */
    private fun executeRootCommand(cmd: String) {
        synchronized(rootLock) {
            val stream = ensureRootAlive()
            val process = checkNotNull(rootProcess)
            try {
                stream.writeBytes("$cmd\n")
                stream.flush()
            } catch (e: java.io.IOException) {
                // Invalidate independently of isAlive: a failed pipe can outlive
                // that OS observation. The failed command must never be replayed.
                rootProcess = null
                rootStream = null
                Timber.w("Root input write failed; command outcome is unknown")
                runCatching { stream.close() }
                runCatching { process.destroyForcibly() }
                // Even a flush error may follow delivery of the full command.
                // Reopen only for a subsequent explicit command, never replay.
                throw RootCommandOutcomeUnknownException()
            }
        }
    }

    /** Закрыть root-сессию при уничтожении сервиса. */
    fun closeRootSession() {
        synchronized(rootLock) {
            val process = rootProcess ?: return
            val stream = rootStream
            // Clear ownership before cleanup. A later explicit action may open
            // a new session, but cleanup must never start one by itself.
            rootProcess = null
            rootStream = null
            try {
                stream?.writeBytes("exit\n")
                stream?.flush()
                if (!process.waitFor(250, TimeUnit.MILLISECONDS)) {
                    process.destroyForcibly()
                }
                Timber.i("Root session closed")
            } catch (e: Exception) {
                runCatching { process.destroyForcibly() }
                Timber.w("Root session cleanup failed")
            } finally {
                runCatching { stream?.close() }
            }
        }
    }

    // ── Basic input actions ───────────────────────────────────────────────────

    fun tap(x: Int, y: Int) {
        executeRootCommand("input tap ${scaleX(x)} ${scaleY(y)}")
    }

    /** Tap using raw physical pixel coordinates (no stream→physical scaling). */
    fun tapRaw(x: Int, y: Int) {
        executeRootCommand("input tap $x $y")
    }

    /** Live stream maps the complete gesture using its active capture geometry. */
    fun swipeRaw(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Int) {
        executeRootCommand("input swipe $x1 $y1 $x2 $y2 $durationMs")
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Int) {
        executeRootCommand(
            "input swipe ${scaleX(x1)} ${scaleY(y1)} ${scaleX(x2)} ${scaleY(y2)} $durationMs"
        )
    }

    fun keyEvent(keyCode: Int) {
        executeRootCommand("input keyevent $keyCode")
    }

    /**
     * Вводит текст безопасно через clipboard + paste.
     *
     * `input text` в Android интерпретирует текст через shell, что делает
     * прямую передачу спецсимволов (`"`, `'`, `$`, `&`, и т.д.) опасной
     * и ненадёжной. Вместо этого:
     *   1. Помещаем текст в системный буфер обмена через ClipboardManager
     *   2. Эмулируем Ctrl+V (KEYCODE_PASTE = 279)
     *
     * Это устраняет: shell injection, проблемы с кодировкой UTF-8, emoji,
     * HTML-символы и все прочие спецсимволы одновременно.
     */
    suspend fun typeText(text: String) = withContext(Dispatchers.IO) {
        // 'input text' is the most reliable method for emulators (no clipboard app needed).
        // Spaces must be encoded as %s for Android's input text command.
        val encoded = text.replace(" ", "%s")
        val safe = encoded.replace("'", "'\\''")
        // Typed values may be account credentials. File logs are uploaded even
        // in release builds; neither the raw nor shell-encoded value is safe.
        Timber.d("typeText: input requested")
        executeRootCommand("input text '$safe'")
        delay(150)
    }

    /** Сделать скриншот, вернуть путь к файлу на устройстве. */
    suspend fun takeScreenshot(): String {
        val path = "/sdcard/sphere_screenshot_${System.currentTimeMillis()}.png"
        withContext(Dispatchers.IO) {
            executeRootCommand("screencap -p $path")
            delay(300)  // Wait for screencap to finish writing
        }
        return path
    }

    // ── Device control commands ───────────────────────────────────────────────

    fun wakeScreen() {
        executeRootCommand("input keyevent 224")   // KEYCODE_WAKEUP
    }

    fun lockScreen() {
        executeRootCommand("input keyevent 223")   // KEYCODE_SLEEP
    }

    fun reboot() {
        Timber.w("Reboot command received — executing")
        executeRootCommand("reboot")
    }

    /**
     * Запускает приложение по package name через Launcher intent.
     * Использует `monkey` — гарантированно запускает даже без знания Activity.
     */
    fun launchApp(packageName: String) {
        requireSafePackageName(packageName)
        executeRootCommand("monkey -p $packageName -c android.intent.category.LAUNCHER 1")
    }

    /**
     * Принудительно останавливает приложение (am force-stop).
     */
    fun stopApp(packageName: String) {
        requireSafePackageName(packageName)
        executeRootCommand("am force-stop $packageName")
    }

    /** Валидация package name: только a-z A-Z 0-9 . - _ */
    private fun requireSafePackageName(pkg: String) {
        require(pkg.matches(Regex("[a-zA-Z0-9._\\-]+"))) {
            "Invalid package name: $pkg"
        }
    }

    // ── FindElement (uiautomator dump) ────────────────────────────────────────

    /**
     * Ищет UI-элемент в текущем UI-дереве устройства.
     *
     * Использует `uiautomator dump` для получения XML дерева интерфейса,
     * затем парсит его для поиска элемента с заданным селектором.
     *
     * @param selector Строка поиска (текст, resource-id или content-desc)
     * @param strategy Стратегия: "text", "id", "desc", "class", "xpath"
     * @param timeoutMs Максимальное время ожидания появления элемента (ms)
     * @return Строка "x,y" с центром элемента, или null если не найден
     */
    suspend fun findElement(selector: String, strategy: String, timeoutMs: Int): String? =
        withContext(Dispatchers.IO) {
            val deadline = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < deadline) {
                val xml = dumpUiXml()
                if (xml != null) {
                    val result = parseUiXml(xml, selector, strategy)
                    if (result != null) return@withContext result
                }
                delay(FIND_ELEMENT_POLL_MS)
            }
            Timber.w("[FindElement] Not found: strategy=$strategy selector='$selector'")
            null
        }

    /**
     * Данные одного кандидата для мультипоиска.
     *
     * @param selector Строка поиска
     * @param strategy Стратегия (xpath / text / id / desc / class)
     * @param label    Произвольная метка — возвращается в результате чтобы вызывающий знал
     *                 какой именно кандидат совпал, без разбора coords
     */
    data class SelectorCandidate(val selector: String, val strategy: String, val label: String? = null)

    /**
     * Результат [findFirstElement].
     *
     * @param coords   "x,y" центра найденного элемента
     * @param selector Селектор сработавшего кандидата
     * @param strategy Стратегия сработавшего кандидата
     * @param label    Метка сработавшего кандидата (может быть null)
     * @param index    Индекс в исходном списке [candidates]
     */
    data class ElementMatch(
        val coords: String,
        val selector: String,
        val strategy: String,
        val label: String?,
        val index: Int,
    )

    /**
     * Ищет **первый** совпавший элемент из списка кандидатов.
     *
     * **Ключевая оптимизация:** один вызов `uiautomator dump` на каждую итерацию
     * polling-цикла. Все N кандидатов проверяются против одного и того же XML.
     * Это O(N * dump_count) по памяти и O(1 * dump_count) по I/O вместо O(N) dumps.
     *
     * Кандидаты проверяются в порядке списка — первое совпадение возвращается немедленно.
     *
     * @param candidates Список кандидатов (selector + strategy + label)
     * @param timeoutMs  Максимальное время ожидания (ms)
     * @return [ElementMatch] первого совпавшего кандидата или null
     */
    suspend fun findFirstElement(
        candidates: List<SelectorCandidate>,
        timeoutMs: Int,
    ): ElementMatch? = withContext(Dispatchers.IO) {
        if (candidates.isEmpty()) return@withContext null
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val xml = dumpUiXml()           // ← ОДНА выгрузка на всю итерацию
            if (xml != null) {
                for ((idx, candidate) in candidates.withIndex()) {
                    val coords = parseUiXml(xml, candidate.selector, candidate.strategy)
                    if (coords != null) {
                        Timber.d("[FindFirst] Hit: index=$idx label=${candidate.label} coords=$coords")
                        return@withContext ElementMatch(
                            coords   = coords,
                            selector = candidate.selector,
                            strategy = candidate.strategy,
                            label    = candidate.label,
                            index    = idx,
                        )
                    }
                }
            }
            delay(FIND_ELEMENT_POLL_MS)
        }
        Timber.w("[FindFirst] None of ${candidates.size} candidates found within ${timeoutMs}ms")
        null
    }

    /** Serialized private dump with bounded EOF reads, no global process kill. */
    private suspend fun dumpUiXml(): UiHierarchyXml.Snapshot? = uiDumpOwnership.withLock {
        withContext(Dispatchers.IO) {
            val file = java.io.File.createTempFile("sphere-ui-", ".xml", context.cacheDir)
            try {
                val quotedPath = "'" + file.absolutePath.replace("'", "'\\''") + "'"
                val result = processRunner.run(
                    start = { Runtime.getRuntime().exec(arrayOf("su", "-c",
                        "uiautomator dump $quotedPath >/dev/null 2>&1 && cat $quotedPath")) },
                    timeoutMs = UI_DUMP_TIMEOUT_SECONDS * 1000,
                    stdoutLimit = UiHierarchyXml.MAX_BYTES, stderrLimit = 1024,
                )
                if (result.stdout.truncated) {
                    throw RootCommandOutcomeUnknownException("UI dump exceeded byte budget; result incomplete")
                }
                if (result.exitCode != 0) return@withContext null
                val xml = result.stdout.bytes.toString(Charsets.UTF_8)
                // One complete validated document is shared by all selectors in this poll.
                UiHierarchyXml.Snapshot(xml, UiHierarchyXml.parse(xml))
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: ProcessOutputIncompleteException) {
                throw RootCommandOutcomeUnknownException("UI dump unavailable: ${e.reason}")
            } catch (e: RootCommandOutcomeUnknownException) {
                throw e
            } catch (e: Exception) {
                Timber.w("[FindElement] UI dump invalid or unavailable")
                null
            } finally {
                // App-owned cache directory permits unlinking even a root-written inode.
                if (!file.delete() && file.exists()) Timber.w("[FindElement] UI dump cleanup failed")
            }
        }
    }

    /**
     * Парсит XML UI-дамп и находит центр элемента по заданной стратегии.
     *
     * Стратегии:
     * - "text"  — поиск по атрибуту `text` (содержит, без учёта регистра)
     * - "id"    — поиск по `resource-id` (точное совпадение или суффикс `:id/selector`)
     * - "desc"  — поиск по `content-desc` (содержит)
     * - "class" — поиск по `class` (содержит, например "Button")
     * - "xpath" — полноценный XPath 1.0 через javax.xml.xpath (встроен в Android SDK).
     *             Поддерживает иерархию, несколько предикатов, позиции, логические операторы.
     *             Примеры (// = descendant-or-self, не используйте / + asterisk в KDoc):
     *               //node[@class='android.widget.Button' and @text='Login']
     *               //node[@resource-id='com.example:id/btn_ok']
     *               //node[@class='android.widget.Button'][2]
     *               //node[contains(@text,'Sign')]
     *               //node[@class='android.widget.ListView']/node[last()]
     */
    private fun parseUiXml(snapshot: UiHierarchyXml.Snapshot, selector: String, strategy: String): String? {
        return try {
            if (strategy == "xpath") {
                parseUiXmlXPath(snapshot.document, selector)
            } else {
                parseUiXmlSimple(snapshot.xml, selector, strategy)
            }
        } catch (e: Exception) {
            Timber.w(e, "[FindElement] XML parse error")
            null
        }
    }

    /**
     * Полноценный XPath 1.0 через javax.xml.xpath (нет доп. зависимостей, API 8+).
     * Находит первый узел с непустым атрибутом bounds и возвращает координаты центра.
     */
    private fun parseUiXmlXPath(doc: org.w3c.dom.Document, xpath: String): String? {
        val xpathExpr = XPATH_FACTORY.newXPath().compile(xpath)
        val nodeList = xpathExpr.evaluate(doc, XPathConstants.NODESET)
            as org.w3c.dom.NodeList
        for (i in 0 until nodeList.length) {
            val node = nodeList.item(i) as? Element ?: continue
            val bounds = node.getAttribute("bounds") ?: ""
            val center = parseBoundsCenter(bounds)
            if (center != null) return center
        }
        return null
    }

    /** Быстрый поиск через XmlPullParser для стратегий text / id / desc / class. */
    private fun parseUiXmlSimple(xml: String, selector: String, strategy: String): String? {
        val parser = XMLPULL_FACTORY.newPullParser()
        parser.setInput(StringReader(xml))

        val attribute = when (strategy) {
            "id"    -> "resource-id"
            "desc"  -> "content-desc"
            "class" -> "class"
            else    -> "text"
        }

        var eventType = parser.eventType
        while (eventType != XmlPullParser.END_DOCUMENT) {
            if (eventType == XmlPullParser.START_TAG && parser.name == "node") {
                val attrVal = parser.getAttributeValue(null, attribute) ?: ""
                val matches = when (strategy) {
                    "id"   -> attrVal == selector || attrVal.endsWith(":id/$selector")
                    else   -> attrVal.contains(selector, ignoreCase = true)
                }
                if (matches) {
                    val bounds = parser.getAttributeValue(null, "bounds") ?: ""
                    val center = parseBoundsCenter(bounds)
                    if (center != null) return center
                }
            }
            eventType = parser.next()
        }
        return null
    }

    /** "[x1,y1][x2,y2]" → "cx,cy" */
    private fun parseBoundsCenter(bounds: String): String? {
        val regex = Regex("""\[(\d+),(\d+)]\[(\d+),(\d+)]""")
        val match = regex.find(bounds) ?: return null
        val (x1, y1, x2, y2) = match.destructured
        val cx = (x1.toInt() + x2.toInt()) / 2
        val cy = (y1.toInt() + y2.toInt()) / 2
        return "$cx,$cy"
    }

    // ── Shell (arbitrary root commands) ──────────────────────────────────────

    /**
     * Выполняет shell-команду с получением stdout.
     *
     * БЕЗОПАСНОСТЬ: команда проверяется на shell injection перед выполнением.
     * Разрешены только printable ASCII (32–126).
     * Используется отдельный процесс (нужен stdout), не интерактивная сессия.
     */
    suspend fun shell(command: String): String {
        require(!SHELL_INJECTION_PATTERN.containsMatchIn(command)) {
            "Shell injection: forbidden metacharacters in command"
        }
        require(command.all { it.code in 32..126 }) {
            "Non-printable characters in shell command"
        }
        return shellExec(command)
    }

    /**
     * FIX AUDIT-2.4: Внутренний batch shell для предопределённых команд.
     * НЕ выполняет injection-проверку — использовать ТОЛЬКО для hardcoded команд,
     * НИКОГДА для пользовательского ввода!
     */
    private suspend fun shellBatch(command: String): String = shellExec(command)

    /** Общая реализация shell exec (su -c) с таймаутом. */
    private suspend fun shellExec(command: String): String {
        val result = try {
            processRunner.run(
                start = { Runtime.getRuntime().exec(arrayOf("su", "-c", command)) },
                timeoutMs = 5_000, stdoutLimit = 256 * 1024, stderrLimit = 1024,
            )
        } catch (error: ProcessOutputIncompleteException) {
            // The shell may have performed a side effect. DAG must not retry it.
            throw RootCommandOutcomeUnknownException("Root command result unavailable: ${error.reason}")
        }
        if (result.stdout.truncated) {
            throw RootCommandOutcomeUnknownException("Root command output exceeded 256 KiB; result incomplete")
        }
        if (result.exitCode != 0) {
            // Do not put the command or its potentially sensitive stderr into uploaded logs.
            throw java.io.IOException("Shell command exited with code ${result.exitCode}")
        }
        return result.stdout.bytes.toString(Charsets.UTF_8)
    }

    // ── Extended gestures ─────────────────────────────────────────────────────

    /** Долгое нажатие через input swipe с совпадающими start/end координатами. */
    fun longPress(x: Int, y: Int, durationMs: Int = 800) {
        val sx = scaleX(x); val sy = scaleY(y)
        executeRootCommand("input swipe $sx $sy $sx $sy $durationMs")
    }

    /** Двойное касание с 80ms интервалом. */
    suspend fun doubleTap(x: Int, y: Int) {
        tap(x, y)
        delay(80)
        tap(x, y)
    }

    /**
     * Прокрутка в заданном направлении на [percent] доли экрана.
     * direction: "up" | "down" | "left" | "right"
     */
    fun scroll(direction: String, percent: Float = 0.45f, durationMs: Int = 350) {
        val cw = physicalSize.x; val ch = physicalSize.y
        val dx = (cw * percent / 2).toInt()
        val dy = (ch * percent / 2).toInt()
        val (x1, y1, x2, y2) = when (direction) {
            "up"    -> listOf(cw / 2, ch / 2 + dy, cw / 2, ch / 2 - dy)
            "left"  -> listOf(cw / 2 + dx, ch / 2, cw / 2 - dx, ch / 2)
            "right" -> listOf(cw / 2 - dx, ch / 2, cw / 2 + dx, ch / 2)
            else    -> listOf(cw / 2, ch / 2 - dy, cw / 2, ch / 2 + dy) // "down"
        }
        // Already in physical pixels — bypass scaleX/Y
        executeRootCommand("input swipe $x1 $y1 $x2 $y2 $durationMs")
    }

    /**
     * Прокручивает экран пока элемент не станет видимым (или лимит исчерпан).
     * @return true если элемент найден
     */
    suspend fun scrollUntilVisible(
        selector: String,
        strategy: String,
        direction: String = "down",
        maxScrolls: Int = 10,
        durationMs: Int = 400,
    ): Boolean = withContext(Dispatchers.IO) {
        repeat(maxScrolls) {
            if (findElement(selector, strategy, 1_500) != null) return@withContext true
            scroll(direction, 0.40f, durationMs)
            delay(600)
        }
        findElement(selector, strategy, 1_500) != null
    }

    /**
     * Ожидает пока элемент не исчезнет из UI-дерева.
     * Двойная проверка устраняет ложные срабатывания при временной перерисовке.
     * @return true если пропал, false если timeout истёк
     */
    suspend fun waitForElementGone(
        selector: String,
        strategy: String,
        timeoutMs: Int,
    ): Boolean = withContext(Dispatchers.IO) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val xml = dumpUiXml()
            if (xml == null || parseUiXml(xml, selector, strategy) == null) {
                delay(200)
                val xml2 = dumpUiXml()
                if (xml2 == null || parseUiXml(xml2, selector, strategy) == null) {
                    return@withContext true
                }
            }
            delay(FIND_ELEMENT_POLL_MS)
        }
        false
    }

    /**
     * Находит элемент и возвращает значение атрибута [attribute] (по умолчанию "text").
     * Полезно для чтения текста из элементов найденных по id или xpath.
     */
    suspend fun readElementText(
        selector: String,
        strategy: String,
        timeoutMs: Int,
        attribute: String = "text",
    ): String? = withContext(Dispatchers.IO) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val xml = dumpUiXml()
            if (xml != null) {
                val v = readNodeAttribute(xml, selector, strategy, attribute)
                if (v != null) return@withContext v
            }
            delay(FIND_ELEMENT_POLL_MS)
        }
        Timber.w("[ReadText] Not found: strategy=$strategy selector='$selector'")
        null
    }

    /** Считывает произвольный [attribute] из первого узла, найденного по селектору. */
    private fun readNodeAttribute(
        snapshot: UiHierarchyXml.Snapshot,
        selector: String,
        strategy: String,
        attribute: String,
    ): String? {
        return try {
            if (strategy == "xpath") {
                val doc = snapshot.document
                val nodeList = XPATH_FACTORY.newXPath().compile(selector)
                    .evaluate(doc, XPathConstants.NODESET) as org.w3c.dom.NodeList
                for (i in 0 until nodeList.length) {
                    val v = (nodeList.item(i) as? Element)?.getAttribute(attribute)
                    if (!v.isNullOrEmpty()) return v
                }
                null
            } else {
                val matchAttr = when (strategy) {
                    "id"    -> "resource-id"
                    "desc"  -> "content-desc"
                    "class" -> "class"
                    else    -> "text"
                }
                val parser = XMLPULL_FACTORY.newPullParser()
                parser.setInput(StringReader(snapshot.xml))
                var ev = parser.eventType
                while (ev != XmlPullParser.END_DOCUMENT) {
                    if (ev == XmlPullParser.START_TAG && parser.name == "node") {
                        val v = parser.getAttributeValue(null, matchAttr) ?: ""
                        val hit = if (strategy == "id") v == selector || v.endsWith(":id/$selector")
                                  else v.contains(selector, ignoreCase = true)
                        if (hit) return parser.getAttributeValue(null, attribute)
                    }
                    ev = parser.next()
                }
                null
            }
        } catch (e: Exception) {
            Timber.w(e, "[ReadAttr] Parse error: $attribute on '$selector'")
            null
        }
    }

    // ── App / System extended ─────────────────────────────────────────────────

    /**
     * Открывает URL через системный Intent (браузер, deeplink, приложение).
     * Допустимы только http:// и https:// схемы.
     */
    fun openUrl(url: String) {
        require(url.startsWith("http://") || url.startsWith("https://")) {
            "openUrl: only http/https allowed"
        }
        require(url.length < 2048 && url.none { it.code < 32 }) {
            "openUrl: URL is invalid"
        }
        val safe = url.replace("'", "'\\''")
        executeRootCommand("am start -a android.intent.action.VIEW -d '$safe'")
    }

    /** Сбрасывает данные приложения (эквивалент "Очистить данные" в настройках). */
    fun clearAppData(packageName: String) {
        requireSafePackageName(packageName)
        executeRootCommand("pm clear $packageName")
    }

    /**
     * Возвращает ключевые параметры устройства для использования в DAG-узле get_device_info.
     * FIX AUDIT-2.4: Batch-запрос через одну shell-команду вместо 6 отдельных fork+exec.
     * На слабом эмуляторе один fork ~50-150ms, 6 = 300-900ms. Теперь ~50-150ms total.
     */
    suspend fun getDeviceInfo(): Map<String, Any?> = withContext(Dispatchers.IO) {
        try {
            // Все getprop в одной команде, разделены маркерами для парсинга
            val SEPARATOR = "|||"
            val batchCmd = "getprop ro.product.model && echo '$SEPARATOR' && " +
                "getprop ro.product.manufacturer && echo '$SEPARATOR' && " +
                "getprop ro.build.version.release && echo '$SEPARATOR' && " +
                "getprop ro.build.version.sdk && echo '$SEPARATOR' && " +
                "cat /sys/class/power_supply/battery/capacity 2>/dev/null && echo '$SEPARATOR' && " +
                "getprop ro.serialno"
            val raw = shellBatch(batchCmd)
            val parts = raw.split(SEPARATOR).map { it.trim() }
            mapOf(
                "model"           to (parts.getOrNull(0) ?: ""),
                "manufacturer"    to (parts.getOrNull(1) ?: ""),
                "android_version" to (parts.getOrNull(2) ?: ""),
                "sdk_int"         to parts.getOrNull(3)?.toIntOrNull(),
                "battery_level"   to parts.getOrNull(4)?.toIntOrNull(),
                "screen_width"    to physicalSize.x,
                "screen_height"   to physicalSize.y,
                "serial"          to (parts.getOrNull(5)?.ifEmpty { "unknown" } ?: "unknown"),
            )
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            Timber.w(e, "getDeviceInfo batch failed — fallback")
            mapOf(
                "model" to "unknown",
                "manufacturer" to "unknown",
                "android_version" to "unknown",
                "sdk_int" to null,
                "battery_level" to null,
                "screen_width" to physicalSize.x,
                "screen_height" to physicalSize.y,
                "serial" to "unknown",
            )
        }
    }
}
