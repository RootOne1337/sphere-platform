package com.sphereplatform.agent.root

import android.content.Context
import io.mockk.every
import io.mockk.mockk
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * Tests for optional, package-scoped root recovery policy.
 *
 * Покрытие:
 *  - configure() без root → тихий пропуск
 *  - no-root startup remains a no-op
 */
class RootAutoStartTest {

    private lateinit var context: Context

    @Before
    fun setUp() {
        context = mockk(relaxed = true)
        every { context.packageName } returns "com.sphereplatform.agent.dev"
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
