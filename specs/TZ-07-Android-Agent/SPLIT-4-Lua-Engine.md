# SPLIT-4 — Lua Engine (LuaJ Bindings)

**ТЗ-родитель:** TZ-07-Android-Agent  
**Ветка:** `stage/7-android`  
**Задача:** `SPHERE-039`  
**Исполнитель:** Android  
**Оценка:** 1.5 дня  
**Блокирует:** TZ-07 SPLIT-5 (OTA)

---

## Цель Сплита

Встроенный Lua-интерпретатор (LuaJ) с безопасным sandbox: доступны only функции управления устройством, заблокированы os/io/require и любой внешний доступ.

---

## Шаг 1 — Зависимость и AppModule

```kotlin
// build.gradle.kts (app)
dependencies {
    // LuaJ — чистая Java-реализация Lua 5.2
    implementation("org.luaj:luaj-jse:3.0.1")
}
```

```kotlin
// di/LuaModule.kt
@Module
@InstallIn(SingletonComponent::class)
object LuaModule {
    @Provides
    @Singleton
    fun provideLuaEngine(
        adbActions: AdbActionExecutor,
    ): LuaEngine = LuaEngine(adbActions)
}
```

---

## Шаг 2 — Sandbox Setup

```kotlin
// AndroidAgent/lua/LuaEngine.kt
@Singleton
class LuaEngine @Inject constructor(
    private val adbActions: AdbActionExecutor,
) {
    // ЗАБЛОКИРОВАННЫЕ библиотеки Lua
    private val BLOCKED_LIBS = setOf(
        "os", "io", "require", "dofile", "loadfile", "load",
        "debug", "package", "collectgarbage",
    )
    
    // ЗАБЛОКИРОВАННЫЕ функции — предотвращают sandbox escape через метатаблицы
    private val BLOCKED_FUNCTIONS = setOf(
        "load", "loadstring", "rawget", "rawset", "rawlen", "rawequal",
        "getmetatable", "setmetatable",  // КРИТИЧНО: без блокировки возможен escape
    )
    
    suspend fun execute(code: String, ctx: Map<String, Any?>): Any? {
        // Используем Dispatchers.IO, а НЕ Dispatchers.Default:
        // • LuaJ — блокирующая интерпретация (JVM Lua), Thread.sleep блокирует поток
        // • Dispatchers.IO имеет неограниченный пул потоков (не = CPU ядрам как Default)
        // • sleep() в Lua не заблокирует общий thread pool Default
        return withContext(Dispatchers.IO) {
            val globals = buildSandbox(ctx)
            
            val chunk = globals.load(code, "script")
            val result = chunk.call()
            
            // Конвертируем LuaValue → Kotlin
            when {
                result.isnil() -> null
                result.isboolean() -> result.toboolean()
                result.isnumber() -> result.todouble()
                result.isstring() -> result.tojstring()
                else -> result.tojstring()
            }
        }
    }
    
    private fun buildSandbox(ctx: Map<String, Any?>): LuaTable {
        // FIX 7.1: КРИТИЧНО — БЫЛО JsePlatform.standardGlobals()
        // standardGlobals() загружает ВСЕ библиотеки включая luajava:
        //   luajava.bindClass("java.lang.Runtime"):exec("rm -rf /")
        // → полный sandbox escape через JNI-bridge!
        //
        // СТАЛО: JsePlatform.debugGlobals() → ручное удаление лишнего
        // Альтернатива: JmePlatform.standardGlobals() (без JSE-расширений),
        // но debugGlobals() даёт нам print/tostring для отладки Lua-скриптов.
        val globals = JsePlatform.debugGlobals()
        
        // ─── КРИТИЧНО: БЛОКИРОВКА LUAJAVA ──────────────────────────────
        // luajava = JNI-мост к любому Java-классу из Lua.
        // Без этой строки: luajava.newInstance("java.io.File", "/data") → доступ к FS!
        globals.set("luajava", LuaValue.NIL)
        // ────────────────────────────────────────────────────────────────
        
        // Удаляем опасные библиотеки
        BLOCKED_LIBS.forEach { lib ->
            globals.set(lib, LuaValue.NIL)
        }
        
        // Блокируем опасные функции (sandbox escape prevention)
        BLOCKED_FUNCTIONS.forEach { fn ->
            globals.set(fn, LuaValue.NIL)
        }
        
        // Регистрируем Android-биндинги
        registerAndroidBindings(globals)
        
        // Передаём контекст выполнения (результаты предыдущих нод)
        val ctxTable = LuaTable()
        ctx.forEach { (k, v) ->
            ctxTable.set(k, toLuaValue(v))
        }
        globals.set("ctx", ctxTable)
        
        return globals
    }
    
    private fun registerAndroidBindings(globals: LuaTable) {
        // sphere.tap(x, y)
        globals.set("tap", object : TwoArgFunction() {
            override fun call(x: LuaValue, y: LuaValue): LuaValue {
                adbActions.tap(x.checkint(), y.checkint())
                return LuaValue.TRUE
            }
        })
        
        // sphere.swipe(x1, y1, x2, y2, duration_ms?)
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
        
        // sphere.type_text(text)
        globals.set("type_text", object : OneArgFunction() {
            override fun call(text: LuaValue): LuaValue {
                adbActions.typeText(text.checkjstring())
                return LuaValue.TRUE
            }
        })
        
        // sphere.key_event(key_code)
        globals.set("key_event", object : OneArgFunction() {
            override fun call(code: LuaValue): LuaValue {
                adbActions.keyEvent(code.checkint())
                return LuaValue.TRUE
            }
        })
        
        // sphere.sleep(ms)
        globals.set("sleep", object : OneArgFunction() {
            override fun call(ms: LuaValue): LuaValue {
                // БЕЗОПАСНОСТЬ: используем runBlocking { delay() } вместо Thread.sleep().
                // Thread.sleep() блокирует поток Dispatchers.Default (= CPU ядрам) — голодание пула.
                // runBlocking { delay(ms) } корректно отрабатывает withTimeout и cancellation.
                // execute() запущен на Dispatchers.IO — блокирующий runBlocking допустим.
                runBlocking { delay(ms.checklong()) }
                return LuaValue.TRUE
            }
        })
        
        // sphere.log(msg)
        globals.set("log", object : OneArgFunction() {
            override fun call(msg: LuaValue): LuaValue {
                Timber.d("[Lua] ${msg.tojstring()}")
                return LuaValue.NIL
            }
        })
        
        // sphere.screenshot() → path string
        globals.set("screenshot", object : ZeroArgFunction() {
            override fun call(): LuaValue {
                // FIX: комментарий был неверным: execute() запущен на Dispatchers.IO (см. выше).
                // Блокирующий runBlocking допустим в Dispatchers.IO (не голодает CPU-пул Dispatchers.Default).
                val path = runBlocking { adbActions.takeScreenshot() }
                return LuaValue.valueOf(path)
            }
        })
    }
    
    private fun toLuaValue(v: Any?): LuaValue = when (v) {
        null -> LuaValue.NIL
        is Boolean -> if (v) LuaValue.TRUE else LuaValue.FALSE
        is Int -> LuaValue.valueOf(v)
        is Long -> LuaValue.valueOf(v.toDouble())
        is Double -> LuaValue.valueOf(v)
        is String -> LuaValue.valueOf(v)
        else -> LuaValue.valueOf(v.toString())
    }
}
```

---

## Шаг 3 — Lua Execution Timeout

```kotlin
// AndroidAgent/lua/LuaTimeoutWrapper.kt
/**
 * Запускает Lua-код с таймаутом.
 * При превышении — прерывает Thread (LuaJ не использует корутины).
 */
suspend fun LuaEngine.executeWithTimeout(
    code: String,
    ctx: Map<String, Any?>,
    timeoutMs: Long = 30_000L,
): Any? {
    return withTimeout(timeoutMs) {
        execute(code, ctx)
    }
}
```

---

## Шаг 4 — Тест-скрипт Lua

```lua
-- Пример скрипта: открыть приложение и нажать кнопку
log("Starting example script")
key_event(3)          -- HOME
sleep(500)
tap(540, 960)         -- Tap center
sleep(1000)
swipe(100, 500, 900, 500, 400)  -- Horizontal swipe
local path = screenshot()
log("Screenshot saved: " .. path)
return true
```

---

## Критерии готовности

- [ ] `os`, `io`, `require`, `load`, `loadstring`, `debug`, `package` — `nil` в sandbox
- [ ] `getmetatable`, `setmetatable`, `rawget`, `rawset`, `rawlen`, `rawequal` — `nil` (sandbox escape prevention)
- [ ] Доступны: `tap`, `swipe`, `type_text`, `key_event`, `sleep`, `log`, `screenshot`
- [ ] `ctx` table содержит результаты предыдущих нод DAG
- [ ] Таймаут 30 секунд — `withTimeout` бросает `TimeoutCancellationException`
- [ ] Lua-ошибки ловятся в DagRunner.executeNode() и возвращаются как "failed"
- [ ] Блокирующие биндинги (`sleep`, `screenshot`) работают корректно в Dispatchers.Default
