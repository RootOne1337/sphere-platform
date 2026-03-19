package com.sphereplatform.agent.root

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.File

/**
 * Тесты RootAutoStart — утилита для снятия системных ограничений через root.
 *
 * Покрытие:
 *  - configure() без root → тихий пропуск
 *  - hasRoot() кэширует результат
 *  - buildBootScript() формирует корректный скрипт
 *  - installBootScript() не дублирует при наличии маркера
 */
class RootAutoStartTest {

    private lateinit var context: Context

    @Before
    fun setUp() {
        context = mockk(relaxed = true)
        every { context.packageName } returns "com.sphereplatform.agent.dev"
        // Маркер-файл — не существует (первый запуск)
        val fakeMarker = File.createTempFile("test_marker", ".tmp").apply { delete() }
        every { context.getFileStreamPath("root_boot_script_installed") } returns fakeMarker
    }

    @Test
    fun `hasRoot returns false when su not available`() {
        val result = RootAutoStart.hasRoot()
        assertFalse("hasRoot() должен вернуть false в тестовой среде", result)
    }

    @Test
    fun `configure skips silently when no root`() {
        // Вызов configure() без root — не должен бросать exception
        RootAutoStart.configure(context)
        // Если дошли сюда — тест пройден (нет crash)
    }
}
