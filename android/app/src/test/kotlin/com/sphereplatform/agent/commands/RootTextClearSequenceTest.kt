package com.sphereplatform.agent.commands

import org.junit.Assert.*
import org.junit.Test

class RootTextClearSequenceTest {
    /** A focused editor model: cursor starts in the middle, clipboard must stay untouched. */
    private class Editor(var text: String) : RootTextClearSequence.Injector {
        val held = mutableSetOf<Int>()
        var selectedAll = false
        var clipboard = "do-not-change"
        var deleted = 0
        var calls = 0
        var rejectAt = -1
        var throwAt = -1
        override fun inject(action: Int, keyCode: Int, metaState: Int): Boolean {
            calls++
            // A failed reply can follow actual delivery: exercise finally releases.
            if (action == 0) held.add(keyCode) else held.remove(keyCode)
            if (calls == throwAt) throw IllegalStateException("fixture private data")
            if (calls == rejectAt) return false
            if (action == 0 && keyCode == 29 && 113 in held && metaState and 0x1000 != 0) selectedAll = true
            if (action == 0 && keyCode == 67) {
                check(113 !in held) { "Deletion must happen after releasing Ctrl" }
                if (selectedAll) text = "" else text = text.dropLast(1)
                deleted++
            }
            if (action == 0 && keyCode == 277) clipboard = text
            return true
        }
    }

    @Test fun `clears all focused text including multiline Unicode without changing clipboard`() {
        for (original in listOf("", "abcdef", "first\nsecond", "Поиск 🌍")) {
            val editor = Editor(original)
            RootTextClearSequence.clear(editor)
            assertEquals("", editor.text)
            assertEquals("do-not-change", editor.clipboard)
            assertTrue(editor.held.isEmpty())
            assertEquals(1, editor.deleted)
        }
    }

    @Test fun `rejected selection stops before deletion and independently releases every key`() {
        for (point in 1..4) {
            val editor = Editor("keep content").apply { rejectAt = point }
            assertThrows(IllegalStateException::class.java) { RootTextClearSequence.clear(editor) }
            assertEquals("keep content", editor.text)
            assertEquals(0, editor.deleted)
            assertTrue(editor.held.isEmpty())
            assertEquals("do-not-change", editor.clipboard)
        }
    }

    @Test fun `exception after key down still releases modifiers and never cuts or repeats deletion`() {
        for (point in 1..6) {
            val editor = Editor("content").apply { throwAt = point }
            assertThrows(IllegalStateException::class.java) { RootTextClearSequence.clear(editor) }
            assertTrue(editor.held.isEmpty())
            assertTrue(editor.deleted <= 1)
            assertEquals("do-not-change", editor.clipboard)
        }
    }
}
