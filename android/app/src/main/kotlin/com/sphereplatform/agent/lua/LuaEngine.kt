package com.sphereplatform.agent.lua

import com.sphereplatform.agent.commands.AdbActionExecutor
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.luaj.vm2.Globals
import org.luaj.vm2.LuaTable
import org.luaj.vm2.LuaValue
import org.luaj.vm2.Varargs
import org.luaj.vm2.lib.OneArgFunction
import org.luaj.vm2.lib.TwoArgFunction
import org.luaj.vm2.lib.VarArgFunction
import org.luaj.vm2.lib.ZeroArgFunction
import org.luaj.vm2.lib.jse.JsePlatform
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/**
 * LuaEngine — встроенный Lua 5.2 интерпретатор (LuaJ) с sandbox.
 *
 * ## Sandbox — что ЗАБЛОКИРОВАНО
 * | Цель | Риск |
 * |---|---|
 * | `luajava` | JNI-мост к любому Java-классу: `luajava.bindClass("java.lang.Runtime"):exec(...)` |
 * | `os`, `io` | Доступ к файловой системе и системным вызовам |
 * | `require`, `dofile`, `loadfile` | Загрузка произвольных модулей |
 * | `load`, `loadstring` | Динамическое выполнение кода |
 * | `debug`, `package` | Инструменты отладки и загрузки модулей |
 * | `getmetatable`, `setmetatable` | Escape через метатаблицы |
 * | `rawget`, `rawset`, `rawlen`, `rawequal` | Обход метаметодов защиты |
 *
 * ## Sandbox — что ДОСТУПНО
 * `tap`, `swipe`, `type_text`, `key_event`, `sleep`, `log`, `screenshot`, `ctx`
 *
 * ## Dispatcher: Dispatchers.IO
 * LuaJ — блокирующий интерпретатор; запускается на IO-пуле (не Default),
 * чтобы не блокировать CPU-bounded пул корутин.
 */
@Singleton
class LuaEngine @Inject constructor(
    private val adbActions: AdbActionExecutor,
) {
    companion object {
        // FIX 7.1: НЕ standardGlobals() — он загружает luajava (JNI-мост)
        // и полный os/io/debug/package → sandbox escape.
        // Используем debugGlobals() + ручная зачистка.
        private val BLOCKED_LIBS = setOf(
            "os", "io", "require", "dofile", "loadfile", "load",
            "debug", "package", "collectgarbage",
            // coroutine — Lua coroutines не прерываются withTimeout корректно;
            // бесконечный coroutine.wrap зависает JVM IO-поток на весь timeout
            "coroutine",
        )
        private val BLOCKED_FUNCTIONS = setOf(
            "load", "loadstring", "rawget", "rawset", "rawlen", "rawequal",
            "getmetatable", "setmetatable",
        )
    }

    suspend fun execute(code: String, ctx: Map<String, Any?> = emptyMap()): Any? {
        // Dispatchers.IO: LuaJ блокирует поток, IO-пул не ограничен = CPU-пул не голодает
        return withContext(Dispatchers.IO) {
            Timber.d("[Lua] execute: ctx keys=${ctx.keys}, types=${ctx.mapValues { it.value?.let { v -> v::class.simpleName } }}")
            val globals = buildSandbox(ctx)
            val chunk = globals.load(code, "script")
            val result = chunk.call()
            val kotlinResult = luaToKotlin(result)
            Timber.d("[Lua] result: $kotlinResult (luaType=${result.typename()})")
            kotlinResult
        }
    }

    private fun buildSandbox(ctx: Map<String, Any?>): Globals {
        val globals = JsePlatform.debugGlobals()

        // КРИТИЧНО: luajava = JNI-мост → любой java класс из Lua
        // luajava.newInstance("java.io.File", "/data") → доступ к FS!
        globals.set("luajava", LuaValue.NIL)

        // Блокируем опасные стандартные библиотеки
        BLOCKED_LIBS.forEach { lib -> globals.set(lib, LuaValue.NIL) }

        // Блокируем функции обхода sandbox через метатаблицы
        BLOCKED_FUNCTIONS.forEach { fn -> globals.set(fn, LuaValue.NIL) }

        // Регистрируем Android-биндинги
        registerAndroidBindings(globals)

        // Передаём контекст выполнения (результаты предыдущих нод DAG)
        val ctxTable = LuaTable()
        ctx.forEach { (k, v) -> ctxTable.set(k, kotlinToLua(v)) }
        globals.set("ctx", ctxTable)

        return globals
    }

    private fun registerAndroidBindings(globals: Globals) {
        // tap(x, y)
        globals.set("tap", object : TwoArgFunction() {
            override fun call(x: LuaValue, y: LuaValue): LuaValue {
                adbActions.tap(x.checkint(), y.checkint())
                return LuaValue.TRUE
            }
        })

        // swipe(x1, y1, x2, y2 [, duration_ms])
        globals.set("swipe", object : VarArgFunction() {
            override fun invoke(args: Varargs): Varargs {
                val x1 = args.checkint(1)
                val y1 = args.checkint(2)
                val x2 = args.checkint(3)
                val y2 = args.checkint(4)
                val dur = if (args.narg() >= 5) args.checkint(5) else 300
                adbActions.swipe(x1, y1, x2, y2, dur)
                return LuaValue.TRUE
            }
        })

        // type_text(text)
        globals.set("type_text", object : OneArgFunction() {
            override fun call(text: LuaValue): LuaValue {
                runBlocking { adbActions.typeText(text.checkjstring()) }
                return LuaValue.TRUE
            }
        })

        // key_event(key_code)
        globals.set("key_event", object : OneArgFunction() {
            override fun call(code: LuaValue): LuaValue {
                adbActions.keyEvent(code.checkint())
                return LuaValue.TRUE
            }
        })

        // sleep(ms)
        globals.set("sleep", object : OneArgFunction() {
            override fun call(ms: LuaValue): LuaValue {
                // execute() запущен на Dispatchers.IO — runBlocking допустим.
                // delay() корректно обрабатывает withTimeout и cancellation.
                runBlocking { delay(ms.checklong()) }
                return LuaValue.TRUE
            }
        })

        // log(msg)
        globals.set("log", object : OneArgFunction() {
            override fun call(msg: LuaValue): LuaValue {
                Timber.d("[Lua] ${msg.tojstring()}")
                return LuaValue.NIL
            }
        })

        // screenshot() → path
        globals.set("screenshot", object : ZeroArgFunction() {
            override fun call(): LuaValue {
                val path = runBlocking { adbActions.takeScreenshot() }
                return LuaValue.valueOf(path)
            }
        })

        // find_element(selector [, strategy [, timeout_ms]]) → "cx,cy" | false
        // Returns "x,y" string on success, false on timeout/not found.
        // strategy: "text" (default), "id", "desc"
        globals.set("find_element", object : VarArgFunction() {
            override fun invoke(args: Varargs): Varargs {
                val selector = args.checkjstring(1)
                val strategy = if (args.narg() >= 2) args.checkjstring(2) else "text"
                val timeoutMs = if (args.narg() >= 3) args.checkint(3) else 10_000
                val result = runBlocking { adbActions.findElement(selector, strategy, timeoutMs) }
                return if (result != null) LuaValue.valueOf(result) else LuaValue.FALSE
            }
        })

        // wake_screen() / lock_screen()
        globals.set("wake_screen", object : ZeroArgFunction() {
            override fun call(): LuaValue {
                adbActions.wakeScreen()
                return LuaValue.TRUE
            }
        })
        globals.set("lock_screen", object : ZeroArgFunction() {
            override fun call(): LuaValue {
                adbActions.lockScreen()
                return LuaValue.TRUE
            }
        })

        // launch_app(package_name) — запустить приложение через Launcher intent
        globals.set("launch_app", object : OneArgFunction() {
            override fun call(pkg: LuaValue): LuaValue {
                adbActions.launchApp(pkg.checkjstring())
                return LuaValue.TRUE
            }
        })

        // stop_app(package_name) — принудительно остановить приложение
        globals.set("stop_app", object : OneArgFunction() {
            override fun call(pkg: LuaValue): LuaValue {
                adbActions.stopApp(pkg.checkjstring())
                return LuaValue.TRUE
            }
        })
    }

    private fun kotlinToLua(v: Any?): LuaValue = when (v) {
        null -> LuaValue.NIL
        is Boolean -> if (v) LuaValue.TRUE else LuaValue.FALSE
        is Int -> LuaValue.valueOf(v)
        is Long -> LuaValue.valueOf(v.toDouble())
        is Double -> LuaValue.valueOf(v)
        is String -> LuaValue.valueOf(v)
        is Map<*, *> -> {
            val table = LuaTable()
            v.forEach { (key, value) -> table.set(key.toString(), kotlinToLua(value)) }
            table
        }
        is List<*> -> {
            val table = LuaTable()
            v.forEachIndexed { i, item -> table.set(i + 1, kotlinToLua(item)) }
            table
        }
        else -> LuaValue.valueOf(v.toString())
    }

    private fun luaToKotlin(v: LuaValue): Any? = when {
        v.isnil() -> null
        v.isboolean() -> v.toboolean()
        v.isnumber() -> if (v.isint()) v.toint() else v.todouble()
        v.isstring() -> v.tojstring()
        else -> v.tojstring()
    }
}
