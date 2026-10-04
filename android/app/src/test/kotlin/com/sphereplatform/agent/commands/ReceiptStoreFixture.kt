package com.sphereplatform.agent.commands

import io.mockk.*

/** Fault-injectable durable store boundary for journal/dispatcher unit tests. */
internal class ReceiptStoreFixture {
    val rows = mutableMapOf<String, CommandReceiptStore.Receipt>()
    var writable = true
    val store = mockk<CommandReceiptStore> {
        every { find(any()) } answers { rows[firstArg()]?.status }
        every { prune(any()) } answers {
            val cutoff = firstArg<Long>() - CommandReceiptStore.RETENTION_MS
            rows.entries.removeAll { it.value.acknowledgedAt < cutoff }
            Unit
        }
        every { record(any()) } answers {
            check(writable) { "receipt_disk_unavailable" }
            firstArg<List<CommandReceiptStore.Receipt>>().forEach { rows.putIfAbsent(it.id, it) }
        }
    }
}
