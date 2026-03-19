package com.sphereplatform.agent.lua

import com.sphereplatform.agent.commands.AdbActionExecutor
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.Runs
import io.mockk.verify
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Тесты LuaEngine — Lua 5.2 интерпретатор с sandbox.
 *
 * Покрытие:
 *  - Базовое выполнение: return значения разных типов
 *  - Sandbox: блокировка ВСЕХ опасных библиотек и функций
 *  - Android-биндинги: tap, swipe, type_text, key_event, sleep, log, screenshot, find_element
 *  - Контекст ctx: передача и чтение значений
 *  - Конвертация типов: kotlinToLua / luaToKotlin
 *  - Ошибки: невалидный Lua-код
 */
class LuaEngineTest {

    private lateinit var adbActions: AdbActionExecutor
    private lateinit var engine: LuaEngine

    @Before
    fun setUp() {
        adbActions = mockk(relaxed = true)
        engine = LuaEngine(adbActions)
    }

    // ── Базовое выполнение ───────────────────────────────────────────────────

    @Test
    fun `return nil → null`() = runTest {
        val result = engine.execute("return nil")
        assertNull(result)
    }

    @Test
    fun `return число → Int`() = runTest {
        val result = engine.execute("return 42")
        assertEquals(42, result)
    }

    @Test
    fun `return дробное число → Double`() = runTest {
        val result = engine.execute("return 3.14")
        assertEquals(3.14, result as Double, 0.001)
    }

    @Test
    fun `return строка → String`() = runTest {
        val result = engine.execute("return 'hello'")
        assertEquals("hello", result)
    }

    @Test
    fun `return true → Boolean`() = runTest {
        assertEquals(true, engine.execute("return true"))
    }

    @Test
    fun `return false → Boolean`() = runTest {
        assertEquals(false, engine.execute("return false"))
    }

    @Test
    fun `арифметика`() = runTest {
        assertEquals(15, engine.execute("return 5 + 10"))
    }

    @Test
    fun `string concat`() = runTest {
        assertEquals("hello world", engine.execute("return 'hello' .. ' ' .. 'world'"))
    }

    @Test
    fun `if-else`() = runTest {
        val code = """
            local x = 10
            if x > 5 then return 'big' else return 'small' end
        """.trimIndent()
        assertEquals("big", engine.execute(code))
    }

    @Test
    fun `local function call`() = runTest {
        val code = """
            local function add(a, b) return a + b end
            return add(3, 4)
        """.trimIndent()
        assertEquals(7, engine.execute(code))
    }

    @Test
    fun `for loop`() = runTest {
        val code = """
            local sum = 0
            for i = 1, 10 do sum = sum + i end
            return sum
        """.trimIndent()
        assertEquals(55, engine.execute(code))
    }

    // ── Sandbox: блокировка библиотек ────────────────────────────────────────

    @Test
    fun `sandbox блокирует os`() = runTest {
        val result = engine.execute("return type(os)")
        assertEquals("nil", result)
    }

    @Test
    fun `sandbox блокирует io`() = runTest {
        assertEquals("nil", engine.execute("return type(io)"))
    }

    @Test
    fun `sandbox блокирует require`() = runTest {
        assertEquals("nil", engine.execute("return type(require)"))
    }

    @Test
    fun `sandbox блокирует dofile`() = runTest {
        assertEquals("nil", engine.execute("return type(dofile)"))
    }

    @Test
    fun `sandbox блокирует loadfile`() = runTest {
        assertEquals("nil", engine.execute("return type(loadfile)"))
    }

    @Test
    fun `sandbox блокирует load`() = runTest {
        assertEquals("nil", engine.execute("return type(load)"))
    }

    @Test
    fun `sandbox блокирует debug`() = runTest {
        assertEquals("nil", engine.execute("return type(debug)"))
    }

    @Test
    fun `sandbox блокирует package`() = runTest {
        assertEquals("nil", engine.execute("return type(package)"))
    }

    @Test
    fun `sandbox блокирует collectgarbage`() = runTest {
        assertEquals("nil", engine.execute("return type(collectgarbage)"))
    }

    @Test
    fun `sandbox блокирует coroutine`() = runTest {
        assertEquals("nil", engine.execute("return type(coroutine)"))
    }

    @Test
    fun `sandbox блокирует luajava (JNI мост)`() = runTest {
        assertEquals("nil", engine.execute("return type(luajava)"))
    }

    // ── Sandbox: блокировка функций обхода ───────────────────────────────────

    @Test
    fun `sandbox блокирует loadstring`() = runTest {
        assertEquals("nil", engine.execute("return type(loadstring)"))
    }

    @Test
    fun `sandbox блокирует rawget`() = runTest {
        assertEquals("nil", engine.execute("return type(rawget)"))
    }

    @Test
    fun `sandbox блокирует rawset`() = runTest {
        assertEquals("nil", engine.execute("return type(rawset)"))
    }

    @Test
    fun `sandbox блокирует rawlen`() = runTest {
        assertEquals("nil", engine.execute("return type(rawlen)"))
    }

    @Test
    fun `sandbox блокирует rawequal`() = runTest {
        assertEquals("nil", engine.execute("return type(rawequal)"))
    }

    @Test
    fun `sandbox блокирует getmetatable`() = runTest {
        assertEquals("nil", engine.execute("return type(getmetatable)"))
    }

    @Test
    fun `sandbox блокирует setmetatable`() = runTest {
        assertEquals("nil", engine.execute("return type(setmetatable)"))
    }

    // ── Попытки побега из sandbox ────────────────────────────────────────────

    @Test(expected = Exception::class)
    fun `побег через os_execute → ошибка`() = runTest {
        engine.execute("os.execute('rm -rf /')")
    }

    @Test(expected = Exception::class)
    fun `побег через io_open → ошибка`() = runTest {
        engine.execute("io.open('/etc/passwd', 'r')")
    }

    @Test(expected = Exception::class)
    fun `побег через require → ошибка`() = runTest {
        engine.execute("require('os').execute('whoami')")
    }

    @Test(expected = Exception::class)
    fun `побег через luajava → ошибка`() = runTest {
        engine.execute("luajava.bindClass('java.lang.Runtime'):exec('id')")
    }

    // ── Безопасные функции доступны ──────────────────────────────────────────

    @Test
    fun `math библиотека доступна`() = runTest {
        val result = engine.execute("return math.sqrt(25)")
        // LuaJ может вернуть Int или Double в зависимости от результата
        assertEquals(5.0, (result as Number).toDouble(), 0.001)
    }

    @Test
    fun `string библиотека доступна`() = runTest {
        assertEquals("HELLO", engine.execute("return string.upper('hello')"))
    }

    @Test
    fun `table библиотека доступна`() = runTest {
        val code = """
            local t = {3, 1, 2}
            table.sort(t)
            return t[1]
        """.trimIndent()
        assertEquals(1, engine.execute(code))
    }

    // ── Android-биндинги ─────────────────────────────────────────────────────

    @Test
    fun `tap вызывает adbActions_tap`() = runTest {
        engine.execute("tap(100, 200)")
        verify { adbActions.tap(100, 200) }
    }

    @Test
    fun `swipe вызывает adbActions_swipe с 4 параметрами`() = runTest {
        engine.execute("swipe(10, 20, 30, 40)")
        verify { adbActions.swipe(10, 20, 30, 40, 300) }
    }

    @Test
    fun `swipe вызывает adbActions_swipe с 5 параметрами`() = runTest {
        engine.execute("swipe(10, 20, 30, 40, 500)")
        verify { adbActions.swipe(10, 20, 30, 40, 500) }
    }

    @Test
    fun `type_text вызывает adbActions_typeText`() = runTest {
        coEvery { adbActions.typeText("hello") } just Runs
        engine.execute("type_text('hello')")
        coVerify { adbActions.typeText("hello") }
    }

    @Test
    fun `key_event вызывает adbActions_keyEvent`() = runTest {
        engine.execute("key_event(66)")
        verify { adbActions.keyEvent(66) }
    }

    @Test
    fun `screenshot возвращает путь`() = runTest {
        coEvery { adbActions.takeScreenshot() } returns "/tmp/screenshot.png"
        val result = engine.execute("return screenshot()")
        assertEquals("/tmp/screenshot.png", result)
    }

    @Test
    fun `find_element возвращает координаты`() = runTest {
        coEvery { adbActions.findElement("OK", "text", any()) } returns "540,960"
        val result = engine.execute("return find_element('OK')")
        assertEquals("540,960", result)
    }

    @Test
    fun `find_element возвращает false если не найден`() = runTest {
        coEvery { adbActions.findElement(any(), any(), any()) } returns null
        val result = engine.execute("return find_element('NOPE')")
        assertEquals(false, result)
    }

    @Test
    fun `wake_screen вызывает adbActions`() = runTest {
        engine.execute("wake_screen()")
        verify { adbActions.wakeScreen() }
    }

    @Test
    fun `lock_screen вызывает adbActions`() = runTest {
        engine.execute("lock_screen()")
        verify { adbActions.lockScreen() }
    }

    @Test
    fun `launch_app вызывает adbActions`() = runTest {
        engine.execute("launch_app('com.example.app')")
        verify { adbActions.launchApp("com.example.app") }
    }

    @Test
    fun `stop_app вызывает adbActions`() = runTest {
        engine.execute("stop_app('com.example.app')")
        verify { adbActions.stopApp("com.example.app") }
    }

    // ── Контекст ctx ─────────────────────────────────────────────────────────

    @Test
    fun `ctx передаётся как таблица с строковыми значениями`() = runTest {
        val result = engine.execute("return ctx.name", mapOf("name" to "test"))
        assertEquals("test", result)
    }

    @Test
    fun `ctx передаётся как таблица с числовыми значениями`() = runTest {
        val result = engine.execute("return ctx.count", mapOf("count" to 42))
        assertEquals(42, result)
    }

    @Test
    fun `ctx передаётся как таблица с boolean значениями`() = runTest {
        val result = engine.execute("return ctx.flag", mapOf("flag" to true))
        assertEquals(true, result)
    }

    @Test
    fun `ctx с nil значением`() = runTest {
        val result = engine.execute("return ctx.missing", mapOf("other" to "value"))
        assertNull(result)
    }

    @Test
    fun `ctx с Map значением → вложенная таблица`() = runTest {
        val ctx = mapOf("data" to mapOf("x" to 10, "y" to 20))
        val result = engine.execute("return ctx.data.x + ctx.data.y", ctx)
        assertEquals(30, result)
    }

    @Test
    fun `ctx с List значением → индексированная таблица`() = runTest {
        val ctx = mapOf("items" to listOf(10, 20, 30))
        val result = engine.execute("return ctx.items[2]", ctx)
        assertEquals(20, result)
    }

    // ── Ошибки ───────────────────────────────────────────────────────────────

    @Test(expected = Exception::class)
    fun `невалидный Lua-код → исключение`() = runTest {
        engine.execute("this is not valid lua!!!")
    }

    @Test(expected = Exception::class)
    fun `runtime ошибка → исключение`() = runTest {
        engine.execute("error('test error')")
    }

    @Test(expected = Exception::class)
    fun `nil index → ошибка`() = runTest {
        engine.execute("local x = nil; return x.foo")
    }
}
