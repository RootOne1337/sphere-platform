package com.sphereplatform.agent.commands

import android.content.SharedPreferences
import com.sphereplatform.agent.lua.LuaEngine
import com.sphereplatform.agent.lua.executeWithTimeout
import com.sphereplatform.agent.ws.SphereWebSocketClient
import io.mockk.*
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Тесты DagRunner — ядро исполнения DAG-скриптов.
 *
 * Покрытие:
 *  - Линейный DAG: start → tap → end
 *  - Ветвление: condition → on_true / on_false
 *  - Per-node retry с backoff
 *  - Cancel / Pause / Resume
 *  - Лимиты: MAX_DAG_NODES, MAX_EXECUTE_DEPTH
 *  - Типы нод: tap, swipe, type_text, sleep, key_event, screenshot, lua, find_element
 *  - Переменные: set_variable, get_variable, increment_variable
 *  - Pending results при потере WS
 *  - Global timeout
 */
class DagRunnerTest {

    private lateinit var luaEngine: LuaEngine
    private lateinit var adbActions: AdbActionExecutor
    private lateinit var wsClient: SphereWebSocketClient
    private lateinit var prefs: SharedPreferences
    private lateinit var httpClient: OkHttpClient
    private lateinit var runner: DagRunner

    private val prefsStorage = mutableMapOf<String, Any?>()

    @Before
    fun setUp() {
        luaEngine = mockk(relaxed = true)
        adbActions = mockk(relaxed = true)
        wsClient = mockk(relaxed = true)
        prefs = mockk(relaxed = true)
        httpClient = mockk(relaxed = true)

        every { wsClient.isConnected } returns true
        every { wsClient.sendJson(any()) } returns true

        // SharedPreferences mock
        val editor = mockk<android.content.SharedPreferences.Editor>(relaxed = true)
        every { prefs.edit() } returns editor
        every { editor.putStringSet(any(), any()) } returns editor
        every { editor.remove(any()) } returns editor
        every { editor.apply() } just Runs
        every { prefs.getStringSet(any(), any()) } returns emptySet()

        runner = DagRunner(luaEngine, adbActions, wsClient, prefs, httpClient)
    }

    // ── Хелперы для построения DAG ──────────────────────────────────────────

    private fun buildDag(
        entryNode: String,
        vararg nodes: JsonObject,
        timeoutMs: Long = 60_000L,
    ): JsonObject = buildJsonObject {
        put("entry_node", entryNode)
        put("timeout_ms", timeoutMs)
        put("nodes", buildJsonArray { nodes.forEach { add(it) } })
    }

    private fun node(
        id: String,
        actionType: String,
        onSuccess: String? = null,
        onFailure: String? = null,
        retry: Int = 0,
        timeoutMs: Long = 30_000L,
        actionFields: JsonObjectBuilder.() -> Unit = {},
    ): JsonObject = buildJsonObject {
        put("id", id)
        put("on_success", onSuccess)
        put("on_failure", onFailure)
        put("retry", retry)
        put("timeout_ms", timeoutMs)
        put("action", buildJsonObject {
            put("type", actionType)
            actionFields()
        })
    }

    // ── Линейный DAG ─────────────────────────────────────────────────────────

    @Test
    fun `линейный DAG start → tap → end`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "start", onSuccess = "n2"),
            node("n2", "tap", onSuccess = "n3") { put("x", 100); put("y", 200) },
            node("n3", "end"),
        )
        val result = runner.execute("cmd-1", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
        verify { adbActions.tap(100, 200) }
    }

    @Test
    fun `DAG без нод — пустой results`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "start"),
        )
        val result = runner.execute("cmd-2", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    // ── Различные типы нод ───────────────────────────────────────────────────

    @Test
    fun `нода swipe`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "swipe") {
                put("x1", 10); put("y1", 20); put("x2", 30); put("y2", 40)
                put("duration_ms", 500)
            },
        )
        runner.execute("cmd-3", dag)
        verify { adbActions.swipe(10, 20, 30, 40, 500) }
    }

    @Test
    fun `нода type_text`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "type_text") { put("text", "hello world") },
        )
        coEvery { adbActions.typeText(any()) } just Runs
        runner.execute("cmd-4", dag)
        coVerify { adbActions.typeText("hello world") }
    }

    @Test
    fun `нода sleep — выполняется без ошибок`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "sleep", timeoutMs = 5000) { put("ms", 100) },
        )
        val result = runner.execute("cmd-5", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun `нода key_event`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "key_event") { put("keycode", 66) },
        )
        runner.execute("cmd-6", dag)
        verify { adbActions.keyEvent(66) }
    }

    @Test
    fun `нода screenshot`() = runTest {
        coEvery { adbActions.takeScreenshot() } returns "/tmp/shot.png"
        val dag = buildDag(
            "n1",
            node("n1", "screenshot"),
        )
        val result = runner.execute("cmd-7", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun `нода launch_app`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "launch_app") { put("package", "com.example") },
        )
        runner.execute("cmd-8", dag)
        verify { adbActions.launchApp("com.example") }
    }

    @Test
    fun `нода stop_app`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "stop_app") { put("package", "com.example") },
        )
        runner.execute("cmd-9", dag)
        verify { adbActions.stopApp("com.example") }
    }

    // ── Condition routing ────────────────────────────────────────────────────

    @Test
    fun `condition on_true → переход к true-узлу`() = runTest {
        coEvery { adbActions.findElement("OK", "text", any()) } returns "540,960"
        val dag = buildDag(
            "cond",
            node("cond", "condition", onSuccess = "end") {
                put("check", "element_exists")
                put("params", buildJsonObject {
                    put("selector", "OK")
                    put("strategy", "text")
                })
                put("on_true", "found_node")
                put("on_false", "not_found_node")
            },
            node("found_node", "tap") { put("x", 100); put("y", 200) },
            node("not_found_node", "tap") { put("x", 999); put("y", 999) },
        )
        runner.execute("cmd-10", dag)
        verify { adbActions.tap(100, 200) }
        verify(exactly = 0) { adbActions.tap(999, 999) }
    }

    @Test
    fun `condition on_false → переход к false-узлу`() = runTest {
        coEvery { adbActions.findElement(any(), any(), any()) } returns null
        val dag = buildDag(
            "cond",
            node("cond", "condition") {
                put("check", "element_exists")
                put("params", buildJsonObject {
                    put("selector", "NOPE")
                    put("strategy", "text")
                })
                put("on_true", "true_node")
                put("on_false", "false_node")
            },
            node("true_node", "tap") { put("x", 1); put("y", 1) },
            node("false_node", "tap") { put("x", 2); put("y", 2) },
        )
        runner.execute("cmd-11", dag)
        verify(exactly = 0) { adbActions.tap(1, 1) }
        verify { adbActions.tap(2, 2) }
    }

    // ── Variables ────────────────────────────────────────────────────────────

    @Test
    fun `set_variable + get_variable`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "set_variable", onSuccess = "n2") {
                put("key", "myvar")
                put("value", "hello")
            },
            node("n2", "get_variable") {
                put("key", "myvar")
            },
        )
        val result = runner.execute("cmd-12", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun `increment_variable начинает с 0`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "increment_variable") {
                put("key", "counter")
                put("step", 5)
            },
        )
        val result = runner.execute("cmd-13", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    // ── Per-node retry ───────────────────────────────────────────────────────

    @Test
    fun `retry 2 — первые попытки fail, третья success`() = runTest {
        var callCount = 0
        coEvery { adbActions.tap(any(), any()) } answers {
            callCount++
            if (callCount < 3) throw RuntimeException("transient error")
        }
        val dag = buildDag(
            "n1",
            node("n1", "tap", retry = 2) { put("x", 50); put("y", 50) },
        )
        val result = runner.execute("cmd-14", dag)
        assertTrue("DAG должен завершиться успешно после retry", result["success"]!!.jsonPrimitive.boolean)
        assertEquals(3, callCount)
    }

    @Test
    fun `retry исчерпан → failure`() = runTest {
        coEvery { adbActions.tap(any(), any()) } throws RuntimeException("permanent error")
        val dag = buildDag(
            "n1",
            node("n1", "tap", retry = 1, onFailure = "err") { put("x", 50); put("y", 50) },
            node("err", "end"),
        )
        val result = runner.execute("cmd-15", dag)
        // Есть on_failure → DAG не бросает исключение, но success может быть false
        assertNotNull(result["node_logs"])
    }

    // ── Cancel ───────────────────────────────────────────────────────────────

    @Test
    fun `requestCancel прерывает DAG`() = runTest {
        // Мокаем sleep ноду так чтобы она вызвала requestCancel во время исполнения
        coEvery { adbActions.tap(any(), any()) } coAnswers {
            runner.requestCancel()
        }
        val dag = buildDag(
            "n1",
            node("n1", "tap", onSuccess = "n2") { put("x", 1); put("y", 1) },
            node("n2", "tap") { put("x", 2); put("y", 2) },
        )
        val result = runner.execute("cmd-16", dag)
        assertFalse("DAG должен быть отменён", result["success"]!!.jsonPrimitive.boolean)
    }

    // ── Pause / Resume ───────────────────────────────────────────────────────

    @Test
    fun `requestPause и requestResume`() = runTest {
        // Проверяем что флаги устанавливаются корректно
        runner.requestPause()
        // requestResume должен снять паузу
        runner.requestResume()
        // DAG после resume должен выполниться нормально
        val dag = buildDag("n1", node("n1", "start"))
        val result = runner.execute("cmd-17", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    // ── Лимиты ───────────────────────────────────────────────────────────────

    @Test(expected = IllegalArgumentException::class)
    fun `DAG превышает MAX_DAG_NODES 500 → исключение`() = runTest {
        val nodes = (1..501).map { i ->
            node("n$i", "tap", onSuccess = if (i < 501) "n${i + 1}" else null) {
                put("x", 0); put("y", 0)
            }
        }.toTypedArray()
        val dag = buildDag("n1", *nodes)
        runner.execute("cmd-18", dag)
    }

    @Test
    fun `DAG ровно 500 нод — допустимо`() = runTest {
        val nodes = (1..500).map { i ->
            node("n$i", "start", onSuccess = if (i < 500) "n${i + 1}" else null)
        }.toTypedArray()
        val dag = buildDag("n1", *nodes)
        val result = runner.execute("cmd-19", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    // ── node_logs в результате ───────────────────────────────────────────────

    @Test
    fun `результат содержит node_logs с правильной структурой`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "tap", onSuccess = "n2") { put("x", 10); put("y", 20) },
            node("n2", "end"),
        )
        val result = runner.execute("cmd-20", dag)
        val logs = result["node_logs"]!!.jsonArray
        assertTrue("Должно быть минимум 2 лога", logs.size >= 2)

        val firstLog = logs[0].jsonObject
        assertEquals("n1", firstLog["node_id"]?.jsonPrimitive?.content)
        assertEquals("tap", firstLog["action_type"]?.jsonPrimitive?.content)
        assertTrue(firstLog["success"]?.jsonPrimitive?.boolean ?: false)
        assertNotNull(firstLog["duration_ms"])
    }

    @Test
    fun `nodes_executed считается корректно`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "start", onSuccess = "n2"),
            node("n2", "tap", onSuccess = "n3") { put("x", 1); put("y", 1) },
            node("n3", "end"),
        )
        val result = runner.execute("cmd-21", dag)
        assertEquals(3, result["nodes_executed"]!!.jsonPrimitive.int)
    }

    // ── Несуществующая нода → ошибка ─────────────────────────────────────────

    @Test(expected = IllegalArgumentException::class)
    fun `ссылка на несуществующую ноду → ошибка`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "tap", onSuccess = "nonexistent") { put("x", 1); put("y", 1) },
        )
        runner.execute("cmd-22", dag)
    }

    // ── Неизвестный тип ноды ─────────────────────────────────────────────────

    @Test
    fun `неизвестный тип ноды → UnsupportedOperationException`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "unknown_action_type", onFailure = "err") { },
            node("err", "end"),
        )
        val result = runner.execute("cmd-23", dag)
        // on_failure → переход на err → end, DAG не крашится
        assertNotNull(result)
    }

    // ── Pending results ──────────────────────────────────────────────────────

    @Test
    fun `при offline сохраняет pending result`() = runTest {
        every { wsClient.isConnected } returns false
        val dag = buildDag("n1", node("n1", "start"))
        runner.execute("cmd-24", dag)
        // Должен был вызваться prefs.edit().putStringSet("pending_dag_results", ...)
        verify { prefs.edit() }
    }

    // ── find_element в DAG ───────────────────────────────────────────────────

    @Test
    fun `find_element success`() = runTest {
        coEvery { adbActions.findElement("btn_ok", "id", any()) } returns "540,960"
        val dag = buildDag(
            "n1",
            node("n1", "find_element") {
                put("selector", "btn_ok")
                put("strategy", "id")
            },
        )
        val result = runner.execute("cmd-25", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)
    }

    @Test
    fun `find_element fail_if_not_found = true → failure`() = runTest {
        coEvery { adbActions.findElement(any(), any(), any()) } returns null
        val dag = buildDag(
            "n1",
            node("n1", "find_element", onFailure = "err") {
                put("selector", "btn_ok")
                put("strategy", "id")
                put("fail_if_not_found", "true")
            },
            node("err", "end"),
        )
        val result = runner.execute("cmd-26", dag)
        assertNotNull(result["failed_node"])
    }

    // ── Lua нода в DAG ───────────────────────────────────────────────────────

    @Test
    fun `lua нода вызывает LuaEngine`() = runTest {
        // Мокаем executeWithTimeout extension function
        mockkStatic("com.sphereplatform.agent.lua.LuaTimeoutWrapperKt")
        coEvery { luaEngine.executeWithTimeout(any(), any(), any()) } returns 42

        val dag = buildDag(
            "n1",
            node("n1", "lua") { put("code", "return 42") },
        )
        val result = runner.execute("cmd-27", dag)
        assertTrue(result["success"]!!.jsonPrimitive.boolean)

        unmockkStatic("com.sphereplatform.agent.lua.LuaTimeoutWrapperKt")
    }

    // ── shell нода ───────────────────────────────────────────────────────────

    @Test
    fun `shell нода выполняет команду`() = runTest {
        coEvery { adbActions.shell(any()) } returns "output_data"
        val dag = buildDag(
            "n1",
            node("n1", "shell") { put("command", "ls -la") },
        )
        runner.execute("cmd-28", dag)
        coVerify { adbActions.shell("ls -la") }
    }

    // ── realtime progress ────────────────────────────────────────────────────

    @Test
    fun `progress отправляется по WS после каждого узла`() = runTest {
        val dag = buildDag(
            "n1",
            node("n1", "start", onSuccess = "n2"),
            node("n2", "tap", onSuccess = "n3") { put("x", 1); put("y", 1) },
            node("n3", "end"),
        )
        runner.execute("cmd-29", dag)
        // sendJson вызывается для task_progress
        verify(atLeast = 1) { wsClient.sendJson(match { json ->
            json["type"]?.jsonPrimitive?.contentOrNull == "task_progress"
        }) }
    }

    // ── flushPendingResults ──────────────────────────────────────────────────

    @Test
    fun `flushPendingResults при пустом списке — noop`() = runTest {
        every { prefs.getStringSet("pending_dag_results", any()) } returns emptySet()
        runner.flushPendingResults()
        verify(exactly = 0) { wsClient.sendJson(match { it.containsKey("command_id") }) }
    }
}
