package com.sphereplatform.agent.commands

import androidx.security.crypto.EncryptedSharedPreferences
import kotlinx.serialization.json.*
import timber.log.Timber
import javax.inject.Inject
import javax.inject.Singleton

/** Durable, bounded receipts for DAGs. IDs are deduplicated for seven days.
 * A recovered running receipt has an unknown outcome and must never be rerun.
 * Pending results are retained until the server acknowledges its DB commit.
 */
@Singleton
class CommandJournal @Inject constructor(private val prefs: EncryptedSharedPreferences) {
    companion object {
        private const val KEY = "command_journal_v1"
        private const val RETENTION_MS = 7L * 24 * 60 * 60 * 1000
        private const val MAX_ENTRIES = 512
        private const val MAX_BYTES = 1024 * 1024
        private const val MAX_RESULT_BYTES = 64 * 1024
    }

    sealed class Claim {
        object Started : Claim()
        data class Existing(val response: JsonObject) : Claim()
    }

    private val active = mutableSetOf<String>()
    // A corrupt journal fails closed. Silently resetting it would repeat actions.
    private val records = prefs.getString(KEY, null)?.let {
        Json.parseToJsonElement(it).jsonObject.toMutableMap()
    } ?: mutableMapOf<String, JsonElement>()

    @Synchronized fun claim(id: String): Claim {
        val existing = records[id]?.jsonObject
        if (existing != null) {
            existing["response"]?.let { return Claim.Existing(it.jsonObject) }
            if (id in active) return Claim.Existing(response(id, "running"))
            return Claim.Existing(complete(id, "failed", "execution_outcome_unknown_after_restart", null))
        }
        check(active.isEmpty()) { "device_execution_busy" }
        val now = System.currentTimeMillis()
        val next = records.filterValues { value ->
            val entry = value.jsonObject
            entry["acknowledged"]?.jsonPrimitive?.booleanOrNull != true ||
                now - entry.getValue("created_at").jsonPrimitive.long < RETENTION_MS
        }.toMutableMap()
        check(next.size < MAX_ENTRIES) { "command_journal_capacity_exhausted" }
        next[id] = buildJsonObject { put("created_at", now) }
        persist(next, reserveResult = true) // Confirm durable receipt before any device action.
        active.add(id)
        return Claim.Started
    }

    @Synchronized fun complete(id: String, status: String, error: String?, result: JsonObject?): JsonObject {
        val entry = records[id]?.jsonObject ?: error("command_receipt_missing")
        entry["response"]?.let { return it.jsonObject }
        var payload = response(id, status, error, result)
        if (payload.toString().toByteArray(Charsets.UTF_8).size > MAX_RESULT_BYTES) {
            payload = response(id, status, error?.take(512), buildJsonObject {
                put("success", status == "completed")
                put("result_truncated", true)
            })
        }
        val next = records.toMutableMap()
        next[id] = buildJsonObject {
            put("created_at", entry.getValue("created_at"))
            put("response", payload)
            put("acknowledged", false)
        }
        persist(next)
        active.remove(id)
        return payload
    }

    @Synchronized fun pending(): List<JsonObject> {
        importLegacyResults()
        records.keys.toList().filter { it !in active && records[it]?.jsonObject?.get("response") == null }
            .forEach { complete(it, "failed", "execution_outcome_unknown_after_restart", null) }
        return records.values.mapNotNull { value ->
        val entry = value.jsonObject
        if (entry["acknowledged"]?.jsonPrimitive?.booleanOrNull == true) null
        else entry["response"]?.jsonObject
        }
    }

    private fun importLegacyResults() {
        val remaining = prefs.getStringSet("pending_dag_results", emptySet())?.toMutableSet() ?: return
        for (raw in remaining.toList()) {
            try {
                val old = Json.parseToJsonElement(raw).jsonObject
                val id = old.getValue("command_id").jsonPrimitive.content
                val result = old.getValue("result").jsonObject
                val next = records.toMutableMap()
                if (id !in next) {
                    if (next.size >= MAX_ENTRIES) break
                    val status = if (result["success"]?.jsonPrimitive?.booleanOrNull == true) "completed" else "failed"
                    var payload = response(id, status, result = result)
                    if (payload.toString().toByteArray(Charsets.UTF_8).size > MAX_RESULT_BYTES) {
                        payload = response(id, status, result = buildJsonObject { put("result_truncated", true) })
                    }
                    next[id] = buildJsonObject {
                        put("created_at", System.currentTimeMillis())
                        put("response", payload)
                        put("acknowledged", false)
                    }
                }
                val migrated = remaining - raw
                persist(next, legacyRemaining = migrated)
                remaining.remove(raw)
            } catch (e: Exception) {
                // Historical code truncated raw JSON. Keep malformed records for
                // diagnosis rather than silently treating an invalid result as success.
                Timber.w(e, "Cannot migrate a legacy DAG result")
            }
        }
    }

    @Synchronized fun acknowledge(id: String) {
        val entry = records[id]?.jsonObject ?: return
        val terminal = entry["response"]?.jsonObject ?: return
        if (entry["acknowledged"]?.jsonPrimitive?.booleanOrNull == true) return
        val next = records.toMutableMap()
        next[id] = buildJsonObject {
            put("created_at", entry.getValue("created_at"))
            // Keep a compact terminal receipt for duplicate deliveries.
            put("response", response(id, terminal.getValue("status").jsonPrimitive.content,
                terminal["error"]?.jsonPrimitive?.contentOrNull))
            put("acknowledged", true)
        }
        persist(next)
    }

    private fun persist(next: MutableMap<String, JsonElement>, reserveResult: Boolean = false,
                        legacyRemaining: Set<String>? = null) {
        val encoded = JsonObject(next).toString()
        // Reserve enough room to persist a terminal result for every active DAG.
        check(encoded.toByteArray(Charsets.UTF_8).size <= MAX_BYTES - if (reserveResult) MAX_RESULT_BYTES else 0) {
            "command_journal_capacity_exhausted"
        }
        val editor = prefs.edit().putString(KEY, encoded)
        legacyRemaining?.let { editor.putStringSet("pending_dag_results", it) }
        check(editor.commit()) { "command_journal_write_failed" }
        records.clear()
        records.putAll(next)
    }

    private fun response(id: String, status: String, error: String? = null, result: JsonObject? = null) =
        buildJsonObject {
            put("type", "command_result")
            put("command_id", id)
            put("status", status)
            error?.let { put("error", it) }
            result?.let { put("result", it) }
        }
}
